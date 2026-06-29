#!/usr/bin/env python3
"""
One-time setup: capture the pairing record + device config over USB.

Plug the iPhone in, tap Trust if asked, then run:
    .venv/bin/python save_pairrecord.py

Writes (both gitignored — they contain your device's private keys / identifiers):
    .pairrecord.plist   the USB trust handshake, reused for wireless connects
    config.json         { udid, hostname, fallback_ip } for iphone_wireless.py
"""
import asyncio
import json
import plistlib
import socket
from pathlib import Path

from pymobiledevice3.lockdown import create_using_usbmux

HERE = Path(__file__).parent


async def main():
    ld = await create_using_usbmux()
    rec = ld.pair_record
    with open(HERE / ".pairrecord.plist", "wb") as f:
        plistlib.dump(rec, f)

    name = ld.short_info.get("DeviceName", "iPhone")
    hostname = name.replace("’", "").replace("'", "").replace(" ", "-") + ".local"
    fallback_ip = None
    try:
        fallback_ip = socket.getaddrinfo(hostname, 62078, family=socket.AF_INET)[0][4][0]
    except Exception:
        pass

    cfg = {"udid": ld.identifier, "hostname": hostname, "fallback_ip": fallback_ip}
    (HERE / "config.json").write_text(json.dumps(cfg, indent=2))

    print("✅ saved .pairrecord.plist and config.json")
    print(f"   UDID:        {cfg['udid']}")
    print(f"   hostname:    {cfg['hostname']}")
    print(f"   fallback_ip: {cfg['fallback_ip']}")
    print("\nNow run:  .venv/bin/python iphone_wireless.py")


if __name__ == "__main__":
    asyncio.run(main())
