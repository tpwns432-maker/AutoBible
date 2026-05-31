#!/bin/bash
# =====================================================================
# AutoBible - macOS build script
#   Run this ON a Mac. Produces dist/AutoBible-mac/ containing
#   AutoBible.app plus the data folders next to it.
#
#   Usage:
#       chmod +x build_mac.sh
#       ./build_mac.sh
# =====================================================================
set -e

cd "$(dirname "$0")"

echo "==> Python / pip check"
PYTHON="${PYTHON:-python3}"
"$PYTHON" --version

echo "==> Installing PyInstaller (in current Python environment)"
"$PYTHON" -m pip install --upgrade pip >/dev/null
"$PYTHON" -m pip install --upgrade pyinstaller

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

echo "==> Building AutoBible.app with PyInstaller"
"$PYTHON" -m PyInstaller --onedir --windowed --noconfirm --clean \
  --name AutoBible $ICON_ARG autobible.py

# Locate the produced .app (PyInstaller may place it at dist/AutoBible.app)
APP=""
if [ -d "dist/AutoBible.app" ]; then
  APP="dist/AutoBible.app"
elif [ -d "dist/AutoBible/AutoBible.app" ]; then
  APP="dist/AutoBible/AutoBible.app"
fi

if [ -z "$APP" ]; then
  echo "ERROR: AutoBible.app was not found under dist/. Check PyInstaller output."
  exit 1
fi

echo "==> Bundling data inside AutoBible.app (survives moving / translocation)"
MACOS="$APP/Contents/MacOS"
if [ -d "bible_versions" ]; then
  mkdir -p "$MACOS/bible_versions"
  cp bible_versions/*.SQLite3 "$MACOS/bible_versions/" 2>/dev/null || true
fi
if [ -d "original_lang" ]; then
  mkdir -p "$MACOS/original_lang"
  cp original_lang/* "$MACOS/original_lang/" 2>/dev/null || true
fi

# Copying into the bundle invalidated the signature; re-sign ad-hoc so macOS
# doesn't report the app as "damaged".
echo "==> Re-signing (ad-hoc) AutoBible.app"
codesign --force --deep --sign - "$APP" || echo "  (codesign failed; continuing)"

echo "==> Assembling distribution folder dist/AutoBible-mac/"
OUT="dist/AutoBible-mac"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$APP" "$OUT/"

echo ""
echo "==> Done."
echo "    App + data are in: $OUT"
echo "    Run it by double-clicking: $OUT/AutoBible.app"
echo ""
echo "    NOTE: On first launch macOS Gatekeeper may block an unsigned app."
echo "    Right-click AutoBible.app -> Open -> Open, or run:"
echo "        xattr -dr com.apple.quarantine \"$OUT/AutoBible.app\""
