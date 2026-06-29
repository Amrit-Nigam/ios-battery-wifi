# ios-battery-wifi

Read your **iPhone's battery level + charging state from your Mac, over Wi-Fi** — no cable,
no Shortcut, no hotspot trick, no jailbreak, no installed app. Works even while the phone
is locked.

```
🔋 iPhone: 46% ⚡ charging   (wireless, 192.168.1.46)
```

## Why this is interesting

The usual tool, `libimobiledevice`, reads battery over **USB** but fails **wirelessly** —
macOS Local Network Privacy silently blocks its mDNS device discovery, so `idevice_id -n`
returns nothing. The common conclusion is "you need a signed, entitled GUI app."

You don't. This:
- **skips discovery** — resolves the phone's `.local` name to its Wi-Fi IP and connects directly, and
- reads battery with a plain lockdown **`get_value`** (a property read, *not* a service
  start), so it needs **no iOS-17 RemoteXPC tunnel** and **no special Mac permissions**.

The iPhone's lockdown service (TCP `62078`, the one Finder uses) stays reachable on Wi-Fi;
with a pairing record from a one-time USB trust, you just ask it for the battery.

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for the full explanation and the libimobiledevice comparison.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# one time: plug the iPhone in, tap "Trust", then:
.venv/bin/python save_pairrecord.py     # saves pairing record + config (both gitignored)
```

## Use

```bash
.venv/bin/python iphone_wireless.py      # phone unplugged, same Wi-Fi
```

## Requirements & notes

- macOS + Python 3, iPhone on the **same Wi-Fi**.
- One-time **USB pairing** to capture the trust handshake (`.pairrecord.plist`).
- **Locked is fine** — the Wi-Fi radio sleeps, so the script probes the port and reads on
  the next wake burst (usually a second or two). Deep, long sleep can refuse until it stirs.
- Tested on iOS 26.5 with `pymobiledevice3` v9.
- `.pairrecord.plist` and `config.json` hold your device's private keys / identifiers —
  they're gitignored. **Never commit them.**

## Files

| File | What |
|------|------|
| `iphone_wireless.py` | the wireless battery reader |
| `save_pairrecord.py` | one-time USB capture of pairing record + config |
| `HOW_IT_WORKS.md`    | how it works + how it differs from libimobiledevice |
| `serve.py`           | optional dashboard (Mac + iPhone + AirPods) |
| `iphone.py`          | USB / Continuity-hotspot quick test |
| `NOTES.md`           | log of every method tried, what worked, dead ends |
