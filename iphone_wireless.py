#!/usr/bin/env python3
"""
Read iPhone battery WIRELESSLY — no USB cable, no Shortcut, no hotspot, no tunnel.

The path that finally works (libimobiledevice's CLI couldn't take it):
  1. Resolve the phone's current Wi-Fi IP from its mDNS .local hostname
     (this works even when the flaky _apple-mobdev2 advert is absent).
  2. Open a plain lockdown-over-TCP session on port 62078 using the pairing
     record captured once over USB (.pairrecord.plist).
  3. Read battery with a lockdown get_value on domain com.apple.mobile.battery —
     no service start, so no iOS 17+ RemoteXPC tunnel is required.

The lockdown port stays open on the phone's Wi-Fi interface while the phone is
awake on the same network; resolving .local handles DHCP address changes. When
the phone is locked the Wi-Fi radio sleeps, so we probe the port cheaply and read
on the next wake burst.

Setup (one time): plug the iPhone in once and run  save_pairrecord.py.
Run:  .venv/bin/python iphone_wireless.py [-v]
"""
import asyncio
import json
import plistlib
import re
import socket
import subprocess
import sys
from pathlib import Path

from pymobiledevice3.lockdown import create_using_tcp

HERE = Path(__file__).parent
PAIR_FILE = HERE / ".pairrecord.plist"
CONFIG_FILE = HERE / "config.json"
LOCKDOWN_PORT = 62078


def load_config():
    """Per-device settings written by save_pairrecord.py (gitignored)."""
    if not CONFIG_FILE.exists():
        sys.exit("No config.json — plug the iPhone in once and run save_pairrecord.py.")
    return json.loads(CONFIG_FILE.read_text())


def wake_phone(hostname, ip=None):
    """Nudge a Wi-Fi-sleeping iPhone so it re-announces and re-opens its lockdown port.

    When the phone is locked its Wi-Fi radio dozes and stops answering pings/TCP (but
    stays *associated* to the AP). Several cheap, independent pokes raise the odds one
    lands during a doze-wake burst:
      - an mDNS browse for _apple-mobdev2 (the advert the phone always services),
      - a fresh multicast resolve of the .local name (bypasses a stale sleep-proxy
        record so we also pick up an IP change), and
      - a couple of bare TCP SYNs at the lockdown port (a connect attempt is itself a
        wake stimulus and primes the neighbor/ARP cache).
    All are best-effort and time-boxed; dns-sd never self-exits, so the timeout IS the
    mechanism — the query has already gone out on the wire by then. Note: none of this
    can wake a phone that has *fully left* the network (ARP incomplete) — only the phone
    rejoining fixes that. This targets the far more common doze case.
    """
    try:
        subprocess.run(["dns-sd", "-B", "_apple-mobdev2._tcp"],
                       capture_output=True, timeout=1.5)
    except Exception:
        pass
    # Re-resolve fresh (also refreshes the OS mDNS cache for the next resolve_ip call).
    try:
        socket.getaddrinfo(hostname, LOCKDOWN_PORT, proto=socket.IPPROTO_TCP)
    except Exception:
        pass
    # Bare SYNs at the lockdown port — a connection attempt is a wake stimulus in itself.
    for target in filter(None, (ip,)):
        try:
            socket.create_connection((target, LOCKDOWN_PORT), timeout=0.4).close()
        except OSError:
            pass


def resolve_ip(hostname, fallback):
    """Current Wi-Fi IP from the phone's .local name, else the saved fallback."""
    try:
        infos = socket.getaddrinfo(hostname, LOCKDOWN_PORT, proto=socket.IPPROTO_TCP)
        for fam in (socket.AF_INET, socket.AF_INET6):
            for info in infos:
                if info[0] == fam:
                    return info[4][0]
    except Exception:
        pass
    return fallback


def default_gateway():
    """The default route's gateway IP — this IS the phone when the Mac is on its hotspot."""
    try:
        out = subprocess.run(["route", "-n", "get", "default"],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"gateway:\s*([0-9.]+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


def candidate_ips(hostname, fallback):
    """Ordered, de-duped IPs to try for the phone: mDNS first, then the default gateway
    (covers Personal Hotspot, where the phone is the router at e.g. 172.20.10.1), then
    the saved fallback. On home Wi-Fi the gateway is the router and just refuses fast."""
    seen, out = set(), []
    for ip in (resolve_ip(hostname, None), default_gateway(), fallback):
        if ip and ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def read_via_libimobiledevice(udid):
    """Fallback reader: libimobiledevice over the network (`ideviceinfo -n`).

    Independent of the pymobiledevice3 / port-62078 path — the two mechanisms miss the
    phone's brief Wi-Fi wake-bursts at different moments, so trying both roughly doubles
    the odds any single poll lands a reading. IP-independent (usbmuxd finds the phone by
    UDID via Bonjour). Returns None on any failure; never raises.
    """
    try:
        out = subprocess.run(
            ["ideviceinfo", "-n", "-u", udid, "-q", "com.apple.mobile.battery"],
            capture_output=True, text=True, timeout=6,
        ).stdout
    except Exception:
        return None
    m = re.search(r"BatteryCurrentCapacity:\s*(\d+)", out)
    if not m:
        return None
    chg = re.search(r"BatteryIsCharging:\s*(\w+)", out)
    return {"level": int(m.group(1)),
            "charging": bool(chg and chg.group(1).lower() == "true"),
            "ip": "wifi (libimobiledevice)"}


def port_open(ip, timeout=0.4):
    """Cheap TCP probe so we only do the slow lockdown handshake when it'll succeed."""
    try:
        with socket.create_connection((ip, LOCKDOWN_PORT), timeout=timeout):
            return True
    except OSError:
        return False


async def _attempt(ip, udid, pair_record):
    ld = await create_using_tcp(hostname=ip, port=LOCKDOWN_PORT, identifier=udid,
                                pair_record=pair_record, autopair=False)
    batt = await ld.get_value(domain="com.apple.mobile.battery")
    lvl = batt.get("BatteryCurrentCapacity")
    if lvl is None:
        raise RuntimeError("no battery value")
    return {"level": lvl, "charging": bool(batt.get("BatteryIsCharging")), "ip": ip}


async def read_battery(verbose=False, wait=60.0):
    """Read battery, waiting out the phone's Wi-Fi sleep with a cheap port probe."""
    if not PAIR_FILE.exists():
        sys.exit("No .pairrecord.plist — plug in once and run save_pairrecord.py first.")
    cfg = load_config()
    pair_record = plistlib.load(open(PAIR_FILE, "rb"))
    udid = cfg["udid"]
    hostname, fallback = cfg["hostname"], cfg.get("fallback_ip")
    # Poke the radio awake first, then resolve — a sleeping phone won't answer either otherwise.
    wake_phone(hostname)
    ips = candidate_ips(hostname, fallback)
    if not ips:
        sys.exit("Could not resolve the phone IP and no fallback_ip set in config.json.")
    if verbose:
        print(f"  probing {ips} :{LOCKDOWN_PORT} for up to {wait:.0f}s ...")
    waited = 0.0
    since_nudge = 0.0
    while waited < wait:
        # Primary: plain lockdown-over-TCP (level + charging, no service start). Try each
        # candidate — mDNS IP, then the default gateway (the phone when on its hotspot).
        for ip in ips:
            if port_open(ip):
                try:
                    return await _attempt(ip, udid, pair_record)
                except Exception as e:
                    if verbose:
                        print(f"  ✗ handshake {type(e).__name__} @ {ip}")
        # Fallback: libimobiledevice's network path catches wake-bursts the probe above misses.
        alt = read_via_libimobiledevice(udid)
        if alt:
            return alt
        # Re-nudge and re-resolve every ~5s: one poke at the start rarely coincides with a
        # doze-wake burst, and re-resolving picks up a DHCP/hotspot address change mid-wait.
        since_nudge += 1.0
        if since_nudge >= 5.0:
            since_nudge = 0.0
            wake_phone(hostname, ips[0])
            new_ips = candidate_ips(hostname, fallback)
            if new_ips and new_ips != ips:
                if verbose:
                    print(f"  ↻ candidates {ips} → {new_ips}")
                ips = new_ips
        await asyncio.sleep(0.6)
        waited += 1.0
    return None


async def main():
    # --json: print {"level","charging","ip"} (or {} if unreachable) for the companion server.
    if "--json" in sys.argv:
        r = await read_battery(wait=15)
        print(json.dumps(r or {}))
        return
    r = await read_battery(verbose="-v" in sys.argv)
    if not r:
        print("❌ couldn't reach iPhone — make sure it's awake on the same Wi-Fi.")
        return
    bolt = " ⚡ charging" if r["charging"] else ""
    print(f"🔋 iPhone: {r['level']}%{bolt}   (wireless, {r['ip']})")


if __name__ == "__main__":
    asyncio.run(main())
