#!/bin/bash
# =====================================================================
# BibleClip - macOS build script
#   Run this ON a Mac. Produces dist/BibleClip-mac/ containing
#   BibleClip.app plus the data folders next to it.
#
#   Usage:
#       chmod +x build_mac.sh
#       ./build_mac.sh
# =====================================================================
set -e

cd "$(dirname "$0")/.."   # packaging/ -> project root

echo "==> Python / pip check"
PYTHON="${PYTHON:-python3}"
"$PYTHON" --version

echo "==> Installing PyInstaller (in current Python environment)"
"$PYTHON" -m pip install --upgrade pip >/dev/null
"$PYTHON" -m pip install --upgrade pyinstaller certifi customtkinter

echo "==> Cleaning previous build output"
rm -rf build dist *.spec

# PyInstaller on macOS needs .icns (not .ico). Generate it from icon.png if
# only the PNG is present (sips ships with macOS).
if [ ! -f "icon.icns" ] && [ -f "icon.png" ]; then
  echo "==> Generating icon.icns from icon.png"
  sips -s format icns icon.png --out icon.icns || echo "  (icns conversion failed)"
fi
ICON_ARG=""
if [ -f "icon.icns" ]; then
  ICON_ARG="--icon=icon.icns"
  echo "==> Using icon.icns"
else
  echo "==> No icon.icns - building without a custom icon"
fi

echo "==> Building BibleClip.app with PyInstaller"
"$PYTHON" -m PyInstaller --onedir --windowed --noconfirm --clean \
  --collect-submodules bibleclip --collect-all customtkinter --name BibleClip $ICON_ARG bibleclip_app.py

# Locate the produced .app (PyInstaller may place it at dist/BibleClip.app)
APP=""
if [ -d "dist/BibleClip.app" ]; then
  APP="dist/BibleClip.app"
elif [ -d "dist/BibleClip/BibleClip.app" ]; then
  APP="dist/BibleClip/BibleClip.app"
fi

if [ -z "$APP" ]; then
  echo "ERROR: BibleClip.app was not found under dist/. Check PyInstaller output."
  exit 1
fi

echo "==> Bundling data inside BibleClip.app (survives moving / translocation)"
MACOS="$APP/Contents/MacOS"
if [ -d "bible_versions" ]; then
  mkdir -p "$MACOS/bible_versions"
  cp bible_versions/*.SQLite3 "$MACOS/bible_versions/" 2>/dev/null || true
fi
if [ -d "original_lang" ]; then
  mkdir -p "$MACOS/original_lang"
  cp original_lang/* "$MACOS/original_lang/" 2>/dev/null || true
fi

# Stamp the real version into Info.plist (PyInstaller leaves 0.0.0)
V=$(python3 -c "import re;print(re.search(r'__version__\s*=\s*\"(.+?)\"', open('bibleclip/_version.py').read()).group(1))" 2>/dev/null || echo "")
if [ -n "$V" ]; then
  PLIST="$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $V" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $V" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $V" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $V" "$PLIST" 2>/dev/null || true
fi

# Copying into the bundle invalidated the signature; re-sign ad-hoc so macOS
# doesn't report the app as "damaged".
echo "==> Re-signing (ad-hoc) BibleClip.app"
codesign --force --deep --sign - "$APP" || echo "  (codesign failed; continuing)"

echo "==> Assembling distribution folder dist/BibleClip-mac/"
OUT="dist/BibleClip-mac"
rm -rf "$OUT"
mkdir -p "$OUT"
# ditto (not cp -R) preserves the code signature; cp -R breaks it -> "damaged"
ditto "$APP" "$OUT/BibleClip.app"

echo ""
echo "==> Done."
echo "    App + data are in: $OUT"
echo "    Run it by double-clicking: $OUT/BibleClip.app"
echo ""
echo "    NOTE: On first launch macOS Gatekeeper may block an unsigned app."
echo "    Right-click BibleClip.app -> Open -> Open, or run:"
echo "        xattr -dr com.apple.quarantine \"$OUT/BibleClip.app\""
