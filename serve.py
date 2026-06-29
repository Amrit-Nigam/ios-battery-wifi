#!/usr/bin/env python3
"""
Battery dashboard server — Mac + iPhone + AirPods battery on one page.

iPhone uses a layered, best-available source (see README / research notes):
  1. USB        — libimobiledevice, level + charging, while cabled       (authoritative)
  2. Shortcut   — Apple Shortcut pushes to /battery/phone, anywhere on Wi-Fi (carries charging)
  3. Continuity — Instant Hotspot log, level only, passive, near the Mac

A background thread refreshes the local sources (Mac, AirPods, USB, hotspot)
every POLL_SECONDS so GET /battery never blocks on a subprocess.

Run:  python3 serve.py            then open http://localhost:8080
"""

import json
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8080
POLL_SECONDS = 30
# A pushed phone reading older than this is considered stale and dropped.
PHONE_PUSH_TTL = 15 * 60  # 15 minutes

# Shared state, guarded by _lock.
_lock = threading.Lock()
_state = {
    "mac": None,
    "airpods": None,
    "phone": None,          # the merged, best-available phone reading
    "_phone_push": None,    # last reading pushed by the Shortcut: {level, charging, ts}
    "updated": 0,
}


# ---------------------------------------------------------------------------
# Source helpers — each returns a dict or None, never raises.
# ---------------------------------------------------------------------------

def _run(cmd, timeout=8):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:
        return ""


def read_mac():
    """pmset -g batt -> {level, charging}."""
    out = _run(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%", out)
    if not m:
        return None
    level = int(m.group(1))
    low = out.lower()
    charging = ("ac power" in low and "discharging" not in low) or "charging" in low
    if "charged" in low:
        charging = True
    return {"level": level, "charging": charging, "source": "pmset"}


def read_airpods():
    """system_profiler SPBluetoothDataType -> {level, left, right, case}.

    Earbud % = min(left, right). Charging state is NOT exposed by macOS for
    AirPods (confirmed via AirBattery source), so it's always None.
    """
    out = _run(["system_profiler", "SPBluetoothDataType", "-json"], timeout=12)
    if not out:
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None

    def walk(node):
        # Find the first connected device that reports an AirPods-style level.
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict) and "device_batteryLevelLeft" in v:
                    return k, v
                found = walk(v)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return None

    hit = walk(data)
    if not hit:
        return None
    name, dev = hit

    def pct(key):
        raw = dev.get(key, "")
        m = re.search(r"(\d+)", str(raw))
        return int(m.group(1)) if m else None

    left, right, case = pct("device_batteryLevelLeft"), pct("device_batteryLevelRight"), pct("device_batteryLevelCase")
    buds = [x for x in (left, right) if x is not None]
    if not buds:
        return None
    return {
        "name": name,
        "level": min(buds),
        "left": left,
        "right": right,
        "case": case,
        "charging": None,  # unavailable on macOS
        "source": "system_profiler",
    }


def read_phone_usb():
    """libimobiledevice over USB -> {level, charging}. None if no cabled phone."""
    udid = _run(["idevice_id", "-l"]).strip().splitlines()
    if not udid:
        return None
    out = _run(["ideviceinfo", "-q", "com.apple.mobile.battery"])
    lvl = re.search(r"BatteryCurrentCapacity:\s*(\d+)", out)
    chg = re.search(r"BatteryIsCharging:\s*(\w+)", out)
    if not lvl:
        return None
    return {
        "level": int(lvl.group(1)),
        "charging": (chg.group(1).lower() == "true") if chg else None,
        "source": "usb",
    }


def read_phone_hotspot():
    """Instant Hotspot unified-log -> {level}. Passive, level only, near Mac."""
    out = _run(
        ["log", "show", "--last", "6m",
         "--predicate", 'eventMessage CONTAINS "SFRemoteHotspotDevice"'],
        timeout=12,
    )
    matches = re.findall(r"battery life:\s*(\d+)", out)
    if not matches:
        return None
    return {"level": int(matches[-1]), "charging": None, "source": "hotspot"}


def best_phone(usb, push, hotspot):
    """Pick the richest fresh phone reading: USB > Shortcut push > hotspot."""
    if usb:
        return usb
    if push and (time.time() - push["ts"]) <= PHONE_PUSH_TTL:
        return {"level": push["level"], "charging": push["charging"], "source": "shortcut"}
    if hotspot:
        return hotspot
    return None


# ---------------------------------------------------------------------------
# Background poller
# ---------------------------------------------------------------------------

def poller():
    while True:
        mac = read_mac()
        airpods = read_airpods()
        usb = read_phone_usb()
        hotspot = read_phone_hotspot()
        with _lock:
            push = _state["_phone_push"]
            _state["mac"] = mac
            _state["airpods"] = airpods
            _state["phone"] = best_phone(usb, push, hotspot)
            _state["updated"] = int(time.time())
        time.sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/battery/phone":
            # Push endpoint for the Apple Shortcut.
            q = parse_qs(u.query)
            try:
                level = int(q.get("level", ["?"])[0])
            except ValueError:
                return self._send(400, json.dumps({"error": "bad level"}))
            charging = q.get("charging", ["0"])[0] in ("1", "true", "True")
            with _lock:
                _state["_phone_push"] = {"level": level, "charging": charging, "ts": time.time()}
                # refresh merged value immediately
                _state["phone"] = best_phone(read_phone_usb(), _state["_phone_push"], None) \
                    or _state["phone"]
            return self._send(200, json.dumps({"ok": True, "level": level, "charging": charging}))

        if u.path == "/battery":
            with _lock:
                payload = {k: _state[k] for k in ("mac", "airpods", "phone", "updated")}
            return self._send(200, json.dumps(payload))

        if u.path in ("/", "/index.html"):
            return self._send(200, DASHBOARD, "text/html")

        self._send(404, json.dumps({"error": "not found"}))


DASHBOARD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Battery</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { font: 16px -apple-system, system-ui, sans-serif; background:#0a0a0c; color:#f5f5f7;
         min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
  .grid { display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
          width:100%; max-width:840px; }
  .card { background:#161619; border:1px solid #26262b; border-radius:20px; padding:24px; }
  .top { display:flex; justify-content:space-between; align-items:baseline; }
  .name { font-size:15px; color:#a1a1aa; letter-spacing:.02em; }
  .pct { font-size:46px; font-weight:600; line-height:1; margin:14px 0 16px; }
  .pct small { font-size:22px; color:#71717a; }
  .bar { height:10px; border-radius:6px; background:#2a2a30; overflow:hidden; }
  .fill { height:100%; border-radius:6px; transition:width .5s, background .3s; }
  .meta { margin-top:14px; font-size:13px; color:#71717a; display:flex; gap:10px; align-items:center; }
  .bolt { color:#34c759; }
  .muted { opacity:.45; }
  .sub { font-size:12px; color:#52525b; margin-top:4px; }
  h1 { font-size:13px; font-weight:500; color:#52525b; text-align:center; margin-bottom:20px;
       letter-spacing:.08em; text-transform:uppercase; grid-column:1/-1; }
  #foot { grid-column:1/-1; text-align:center; font-size:12px; color:#3f3f46; margin-top:4px; }
</style></head>
<body><div class="grid" id="grid">
  <h1>Battery</h1>
  <div id="cards"></div>
  <div id="foot">loading…</div>
</div>
<script>
const color = p => p == null ? '#3f3f46' : p <= 20 ? '#ff453a' : p <= 40 ? '#ffd60a' : '#34c759';
function card(name, d) {
  if (!d) return `<div class="card"><div class="top"><span class="name">${name}</span></div>
    <div class="pct muted">—</div><div class="bar"></div>
    <div class="meta muted">no data</div></div>`;
  const p = d.level;
  const bolt = d.charging ? '<span class="bolt">⚡︎ charging</span>' : '';
  const src = d.source ? `<span>via ${d.source}</span>` : '';
  let extra = '';
  if (d.left != null || d.right != null || d.case != null)
    extra = `<div class="sub">L ${d.left ?? '–'}%  ·  R ${d.right ?? '–'}%  ·  case ${d.case ?? '–'}%</div>`;
  return `<div class="card"><div class="top"><span class="name">${name}</span></div>
    <div class="pct">${p}<small>%</small></div>
    <div class="bar"><div class="fill" style="width:${p}%;background:${color(p)}"></div></div>
    ${extra}<div class="meta">${bolt}${bolt&&src?'·':''}${src}</div></div>`;
}
async function tick() {
  try {
    const r = await fetch('/battery'); const d = await r.json();
    document.getElementById('cards').outerHTML =
      `<div id="cards" style="display:contents">
        ${card('Mac', d.mac)}${card('iPhone', d.phone)}${card(d.airpods?.name || 'AirPods', d.airpods)}
      </div>`;
    const age = d.updated ? Math.max(0, Math.round(Date.now()/1000 - d.updated)) : '?';
    document.getElementById('foot').textContent = `updated ${age}s ago`;
  } catch (e) { document.getElementById('foot').textContent = 'server unreachable'; }
}
tick(); setInterval(tick, 5000);
</script></body></html>"""


def main():
    threading.Thread(target=poller, daemon=True).start()
    # do one synchronous poll so the first page load has data
    with _lock:
        _state["mac"] = read_mac()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Battery dashboard:  http://localhost:{PORT}")
    print(f"Shortcut push URL:  http://<your-mac-ip>:{PORT}/battery/phone?level=NN&charging=1")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
