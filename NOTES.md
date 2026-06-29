# Battery research notes

Legend: ✅ works · ⚠️ works with caveats · ❌ dead end

---

## ✅✅ BREAKTHROUGH — wireless iPhone battery, no cable / Shortcut / hotspot / tunnel

**`iphone_wireless.py`** reads level **+ charging** over Wi-Fi with the phone fully
unplugged. This was the open question the old notes called "effectively impossible
without a signed, entitled GUI app." It is possible from plain Python:

The chain:
1. **pymobiledevice3** (pure-Python libimobiledevice) instead of the C CLI.
2. **Pair once over USB** → save the pairing record to `.pairrecord.plist`
   (`save_pairrecord.py`). Contains `WiFiMACAddress` + `EscrowBag`.
3. **Resolve the phone's Wi-Fi IP from its mDNS `.local` name**
   (`socket.getaddrinfo("Amritttts-iPhone.local")` → `192.168.1.46`). This works
   even when the `_apple-mobdev2._tcp` advert is absent.
4. **Connect lockdown-over-TCP to `<ip>:62078`** with the saved pair record.
5. **`lockdown.get_value(domain="com.apple.mobile.battery")`** → `BatteryCurrentCapacity`
   + `BatteryIsCharging`. A plain get_value, *not* a service start — so it needs
   **no iOS 17+ RemoteXPC tunnel** (which would need sudo + a TUN device).

### Why the old notes thought it was blocked
- They used the **C libimobiledevice CLI**. Its wireless discovery rides the system
  `mDNSResponder`, which macOS **Local Network privacy** gates for non-entitled CLIs
  → `idevice_id -n` always empty. pymobiledevice3 does its own multicast browse and,
  more importantly, **we skip discovery entirely** by resolving `.local` + connecting
  to a known IP.
- The lockdown **port 62078 stays open on the phone's Wi-Fi interface** whenever the
  phone is awake on the same network — confirmed with `nc -z 192.168.1.46 62078`.

### Caveats / gotchas
- **mobdev2 Bonjour discovery is flaky** and basically only advertises while the phone
  is **plugged in**. Don't rely on `browse_mobdev2`; resolve `.local` instead (kept as
  the primary path) with a hardcoded `FALLBACK_IP`.
- **Works even while the phone is LOCKED** — but intermittently: iOS only wakes the
  Wi-Fi radio in bursts when locked, so a single connect often times out. The reader
  **retries (8× / 2s)** to catch a wake window; that makes locked reads reliable.
  Phone must be on the same Wi-Fi (not in deep/long sleep with Wi-Fi fully parked).
- DHCP can change the IP → `.local` resolution handles it; update `FALLBACK_IP` rarely.
- pymobiledevice3 v9 API is **fully async** (`create_using_tcp`, `get_value`,
  `browse_mobdev2` are all coroutines).
- Starting a *service* (e.g. `diagnostics_relay`) over plain TCP lockdown →
  `ConnectionTerminatedError` on iOS 17+. Stick to `get_value`.

---

## Mac — ✅ `pmset -g batt` → percentage + charging. Cheap, instant.

## AirPods — ⚠️ levels only
`system_profiler SPBluetoothDataType -json` → `device_batteryLevelLeft/Right/Case`.
Earbuds % = min(L, R). **Charging state not available** (macOS exposes no flag;
AirBattery hardcodes `isCharging: 0`).

## iPhone — older methods (kept for reference; superseded by the breakthrough above)

### libimobiledevice over USB — ✅ but only while cabled
`ideviceinfo -q com.apple.mobile.battery` → `BatteryCurrentCapacity` + `BatteryIsCharging`.

### libimobiledevice over Wi-Fi (`ideviceinfo -n`) — ❌ blocked
Local Network privacy gates the C CLI's mDNS browse. **Superseded** — use
`iphone_wireless.py`.

### Apple Shortcut push — ✅ works anywhere on Wi-Fi, carries charging
Shortcut: Get Battery Level → Get Contents of URL `…/battery/phone?level=<BatteryLevel>&charging=1`.
Needs iPhone-side automation setup. Good wireless fallback; no Mac permission needed.

### Continuity / Instant Hotspot — ⚠️ passive level only, near the Mac
Parse unified log for `SFRemoteHotspotDevice … battery life: N`. No charging.

---

## Files in this repo
- `iphone_wireless.py` — ✅ the wireless reader (level + charging, no cable)
- `save_pairrecord.py` — one-time USB pairing-record capture
- `iphone.py`          — USB / hotspot quick test
- `serve.py`           — dashboard server (Mac + iPhone + AirPods), layered sources
