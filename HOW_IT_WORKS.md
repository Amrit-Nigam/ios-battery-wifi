# Reading iPhone battery from a Mac — wirelessly, no app, no cable

**Result:** a Python script on the Mac reads the iPhone's battery **level + charging
state** over Wi-Fi, with the phone unplugged and even **locked** — no Shortcut, no
hotspot trick, no jailbreak, no signed/entitled GUI app.

```
🔋 iPhone: 46% ⚡ charging   (wireless, 192.168.1.46)
```

---

## The short version

The iPhone runs a tiny service called **lockdown** on TCP port **62078**. It's the same
service Finder/iTunes talk to. It listens on the phone's **Wi-Fi** interface, not just
USB. If you have a valid **pairing record** (the trust handshake you do once over USB),
you can open a lockdown session to the phone over Wi-Fi and just **ask it for the battery
domain** — no special permissions on the Mac required.

Five steps:

1. **Pair once over USB** → save the pairing record to a file (`.pairrecord.plist`).
2. **Find the phone's current Wi-Fi IP** by resolving its mDNS name
   (`Amritttts-iPhone.local` → `192.168.1.46`).
3. **Open lockdown over TCP** to `192.168.1.46:62078` using the saved pairing record.
4. **Read the value** `lockdown.get_value(domain="com.apple.mobile.battery")`
   → `BatteryCurrentCapacity` (%) + `BatteryIsCharging` (bool).
5. (Phone locked?) The Wi-Fi radio sleeps and only wakes in bursts, so we **probe the
   port cheaply and wait for a wake window**, then read.

That's it. The phone willingly hands over its battery to a trusted, paired host.

---

## How this differs from the "libimobiledevice" path (the important part)

`libimobiledevice` is the classic C toolkit (`ideviceinfo`, `idevice_id`, …). Over **USB**
it reads the battery fine. The moment you try it **wirelessly** it dies — and that's the
wall most people hit and conclude "you can't get iPhone battery over Wi-Fi without an app."

Here's *why* it dies, and *why our path doesn't*:

| | libimobiledevice (C CLI) — wireless | This approach (pymobiledevice3) |
|---|---|---|
| **How it finds the phone** | Asks macOS's system mDNS responder to browse for `_apple-mobdev2._tcp` | Doesn't browse at all — resolves the phone's `.local` name to an IP and connects directly |
| **The blocker** | macOS **Local Network Privacy** silently blocks a non-GUI/CLI tool's mDNS browse → `idevice_id -n` returns **nothing**, forever | We sidestep discovery, so there's nothing to block |
| **Why an app "works"** | A signed GUI app (e.g. AirBattery) holds the **Local Network entitlement** and is approved in System Settings, so *its* browse succeeds | We don't need the entitlement because we don't rely on the gated browse |
| **iOS 17+ services** | Many services now require a **RemoteXPC tunnel** (needs `sudo` + a virtual network device) | We use a **`get_value`**, which is a plain lockdown property read — **not** a service start — so **no tunnel needed** |

### In one sentence
**libimobiledevice fails wirelessly because macOS blocks its *device discovery*, not the
connection itself.** We skip discovery entirely (resolve the IP a different way) and read
battery via a lightweight property query that doesn't trip the iOS-17 tunnel requirement —
so the same lockdown port the C tool *could* have used becomes reachable from plain Python
with zero special Mac permissions.

The two "different mechanism" wins:
- **Discovery:** mDNS `.local` resolution / known IP, instead of the privacy-gated
  `_apple-mobdev2` browse.
- **Read method:** `lockdown.get_value(com.apple.mobile.battery)` (a property read),
  instead of starting the diagnostics *service* (which iOS 17+ hides behind a tunnel).

---

## Requirements & caveats

- **One-time USB pairing** to capture the pairing record. After that it's fully wireless.
- Phone and Mac on the **same Wi-Fi**.
- **Locked is fine**, but the Wi-Fi radio sleeps — a single connect can time out, so the
  script polls the port and reads on the next wake burst (usually within a second or two).
  Deep multi-hour sleep with the radio fully parked can still refuse until the phone stirs.
- Tested on **iOS 26.5** with **pymobiledevice3 v9** (whose API is fully async).

## The whole read, in ~5 lines of Python

```python
pair_record = plistlib.load(open(".pairrecord.plist", "rb"))
ip = resolve_via_mdns("Amritttts-iPhone.local")          # -> 192.168.1.46
ld = await create_using_tcp(ip, port=62078, pair_record=pair_record)
batt = await ld.get_value(domain="com.apple.mobile.battery")
print(batt["BatteryCurrentCapacity"], batt["BatteryIsCharging"])
```
