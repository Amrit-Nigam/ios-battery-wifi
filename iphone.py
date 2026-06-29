#!/usr/bin/env python3
"""
Test getting the iPhone battery from this Mac.

Tries each source, best first, and prints whichever works:
  1. USB        — libimobiledevice (level + charging) while cabled
  2. Continuity — Instant Hotspot log (level only) while phone is near the Mac

Run:  python3 iphone.py
"""

import re
import subprocess


def run(cmd, timeout=12):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def via_usb():
    udids = run(["idevice_id", "-l"]).strip().splitlines()
    if not udids:
        return None, "no iPhone on USB (cable it and tap Trust)"
    out = run(["ideviceinfo", "-q", "com.apple.mobile.battery"])
    lvl = re.search(r"BatteryCurrentCapacity:\s*(\d+)", out)
    chg = re.search(r"BatteryIsCharging:\s*(\w+)", out)
    if not lvl:
        return None, "USB device found but battery not readable (run: idevicepair pair)"
    charging = chg and chg.group(1).lower() == "true"
    return {"level": int(lvl.group(1)), "charging": bool(charging), "source": "usb"}, None


def via_hotspot():
    out = run(["log", "show", "--last", "30m",
               "--predicate", 'eventMessage CONTAINS "SFRemoteHotspotDevice"'])
    m = re.findall(r"battery life:\s*(\d+)", out)
    if not m:
        return None, "no Instant Hotspot reading (phone not near Mac / not broadcasting)"
    return {"level": int(m[-1]), "charging": None, "source": "hotspot"}, None


def main():
    print("Testing iPhone battery sources...\n")
    for name, fn in (("USB", via_usb), ("Continuity hotspot", via_hotspot)):
        result, err = fn()
        if result:
            bolt = " ⚡ charging" if result["charging"] else (
                "" if result["charging"] is None else " (not charging)")
            print(f"✅ {name}: {result['level']}%{bolt}   [{result['source']}]")
            return
        print(f"⏭  {name}: {err}")
    print("\nNo source available. Quickest fix: plug the iPhone in via USB and tap Trust.")


if __name__ == "__main__":
    main()
