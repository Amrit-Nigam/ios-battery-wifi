# iPhone & Claude — menu bar app

A native macOS menu bar app (Swift/Cocoa, no Python) showing, left to right:

- **iPhone battery** — SF Symbol `iphone` + level. While charging, the glyph becomes a white
  **Lucide `zap`** symbol instead of the phone (the bolt can't go inside the phone glyph).
- **Claude loader** — a procedurally drawn pixel animation whose look reflects Claude Code's
  state, with the current status text beside it:
  | State | Loader |
  |-------|--------|
  | thinking / tool | **bloom**, orange `#DE7356` |
  | waiting / permission | **bloom**, yellow `#F2F204` |
  | done | **bloom**, green `#04F20B` |
  | idle / offline | **brew** (steaming coffee cup), adaptive tint |

No Mac battery (macOS already shows that natively). Nothing is bundled — both loaders are drawn
in code, ported from the supplied `pixloader` canvas scripts.

## Sounds

A one-shot system sound plays when Claude's state transitions:

- **done** → `Glass`
- **waiting / permission** → `Ping`

Toggle with **Play sounds** in the dropdown (persisted; default on).

## Data source

Read from the local status server on **port 4040** (`~/.claude/statusbar/serve.py`):

- `GET /battery` → `phone.{level,charging,present,…}`
- `GET /status`  → `{state,label,tool,project}`

## Build, install & run

```sh
./build.sh            # -> build/iPhone & Claude.app  (universal, ad-hoc signed)
./build.sh --install  # also copies it to /Applications and launches it
./build.sh --dmg      # also -> build/iPhone & Claude.dmg
```

Once installed, relaunch anytime from **Spotlight / Launchpad** (search "iPhone & Claude"), or:

```sh
open "/Applications/iPhone & Claude.app"
```

- **Quit** from the dropdown; reopen from Spotlight/Launchpad.
- **Start at login** — toggle in the dropdown (macOS 13+); uses `SMAppService` to register the
  app as a login item, so it starts with your Mac.
- The 4040 server must be running. First launch of an ad-hoc-signed app may need **right-click → Open**.

## Credits

- Loader animations (bloom / brew): user-supplied `pixloader` canvas scripts, ported to Core Graphics.
- Menu bar app structure / packaging reference: [m1ckc3s/claude-status-bar](https://github.com/m1ckc3s/claude-status-bar)
- Charging glyph: [Lucide](https://lucide.dev) `zap`
