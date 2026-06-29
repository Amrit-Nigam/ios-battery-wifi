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
import socket
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
    ip = resolve_ip(cfg["hostname"], cfg.get("fallback_ip"))
    if not ip:
        sys.exit("Could not resolve the phone IP and no fallback_ip set in config.json.")
    if verbose:
        print(f"  probing {ip}:{LOCKDOWN_PORT} for up to {wait:.0f}s ...")
    waited = 0.0
    while waited < wait:
        if port_open(ip):
            try:
                return await _attempt(ip, cfg["udid"], pair_record)
            except Exception as e:
                if verbose:
                    print(f"  ✗ handshake {type(e).__name__}")
        await asyncio.sleep(0.6)
        waited += 1.0
    return None


async def main():
    r = await read_battery(verbose="-v" in sys.argv)
    if not r:
        print("❌ couldn't reach iPhone — make sure it's awake on the same Wi-Fi.")
        return
    bolt = " ⚡ charging" if r["charging"] else ""
    print(f"🔋 iPhone: {r['level']}%{bolt}   (wireless, {r['ip']})")


if __name__ == "__main__":
    asyncio.run(main())
