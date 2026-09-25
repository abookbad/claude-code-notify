#!/bin/bash
# Builds, signs and installs "/Applications/Claude Code Notify.app".
# Usage: ./build-app.sh [bundle-id]     (default: com.$USER.claudecode.notify)
set -euo pipefail
cd "$(dirname "$0")"

BUNDLE_ID="${1:-com.$(id -un | tr -cd 'a-zA-Z0-9').claudecode.notify}"
APP="/Applications/Claude Code Notify.app"
IDENTITY="Claude Notify Local Signing"
BUILD="$(mktemp -d)"

command -v swiftc >/dev/null || { echo "swiftc missing: run  xcode-select --install"; exit 1; }

# 1. Compile. -target is REQUIRED: swiftc can default to a newer macOS than the
#    one installed and the app then refuses to launch (LaunchServices -10825).
ARCH="$(uname -m)"   # arm64 or x86_64
swiftc -O -target "$ARCH-apple-macos13.0" -framework UserNotifications \
  -o "$BUILD/notify" main.swift

# 2. Assemble the bundle.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/notify" "$APP/Contents/MacOS/notify"
[ -f AppIcon.icns ] && cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDisplayName</key><string>Claude Code</string>
  <key>CFBundleExecutable</key><string>notify</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Claude Code</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict></plist>
PLIST

# 3. Sign with a self-signed identity. Ad-hoc signing (codesign -s -) is
#    silently REFUSED notification permission on recent macOS, so create a
#    local code-signing cert once if there isn't one.
if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
  echo "Creating local code-signing identity \"$IDENTITY\" (one time)..."
  T="$(mktemp -d)"; PW="notify-$RANDOM$RANDOM"
  cat > "$T/cfg" <<CFG
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=$IDENTITY
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
CFG
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$T/cfg" \
    -keyout "$T/key.pem" -out "$T/cert.pem" 2>/dev/null
  # -legacy + a real password: macOS rejects OpenSSL 3's default PKCS12 MAC and empty passwords.
  LEGACY=""; openssl pkcs12 -help 2>&1 | grep -q -- -legacy && LEGACY="-legacy"
  openssl pkcs12 -export $LEGACY -inkey "$T/key.pem" -in "$T/cert.pem" \
    -name "$IDENTITY" -out "$T/id.p12" -passout "pass:$PW"
  security import "$T/id.p12" -k ~/Library/Keychains/login.keychain-db \
    -P "$PW" -T /usr/bin/codesign
  rm -rf "$T"
fi
codesign --force --sign "$IDENTITY" --identifier "$BUNDLE_ID" "$APP"
codesign -v "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"

# 4. Fire a test banner. The FIRST run asks for notification permission.
"$APP/Contents/MacOS/notify" '{"title":"Claude Code","subtitle":"install test","body":"Done","sound":"none"}' \
  && echo "Installed: $APP ($BUNDLE_ID)" \
  || echo "Posted with an error. Open System Settings > Notifications > Claude Code and allow it, then re-run the test line."
rm -rf "$BUILD"
