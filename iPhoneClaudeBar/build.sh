#!/bin/bash
# Builds "claudestatus.app" (and optionally a .dmg with: ./build.sh --dmg).
# Adapted from the layout/packaging approach in m1ckc3s/claude-status-bar.
set -euo pipefail
cd "$(dirname "$0")"

NAME="claudestatus"
APP="build/$NAME.app"
BIN="$APP/Contents/MacOS/iPhoneClaudeBar"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "Compiling universal binary (arm64 + x86_64)…"
# Two single-arch compiles joined by lipo, with the deployment target pinned so the binary
# runs on older macOS than the build machine.
swiftc -O -target arm64-apple-macos12.0  Sources/*.swift -o "$BIN.arm64"  -framework Cocoa
swiftc -O -target x86_64-apple-macos12.0 Sources/*.swift -o "$BIN.x86_64" -framework Cocoa
lipo -create "$BIN.arm64" "$BIN.x86_64" -output "$BIN"
rm -f "$BIN.arm64" "$BIN.x86_64"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>claudestatus</string>
  <key>CFBundleDisplayName</key><string>claudestatus</string>
  <key>CFBundleIdentifier</key><string>com.local.claudestatus</string>
  <key>CFBundleExecutable</key><string>iPhoneClaudeBar</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST

# App icon (the creature itself is drawn procedurally — no other assets needed).
cp assets/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"

# Ad-hoc sign so it launches locally without a Developer ID (users right-click > Open once).
xattr -cr "$APP"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"

# ./build.sh --install  -> copy into /Applications so it's a proper, always-available app
# (launch from Spotlight/Launchpad, and a stable path for the "Start at login" item).
if [[ "${1:-}" == "--install" ]]; then
  DEST="/Applications/$NAME.app"
  # Quit a running copy so the bundle can be replaced cleanly.
  pkill -f "iPhoneClaudeBar" 2>/dev/null || true
  sleep 1
  rm -rf "$DEST"
  cp -R "$APP" "$DEST"
  echo "Installed $DEST"
  open "$DEST"
fi

if [[ "${1:-}" == "--dmg" ]]; then
  echo "Packaging DMG…"
  DMG="build/$NAME.dmg"
  STAGE="build/dmg-stage"
  rm -rf "$STAGE" "$DMG"
  mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
  echo "Built $DMG"
fi
