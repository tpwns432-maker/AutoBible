# Build the BibleClip web UI (pywebview) into a frozen onedir app on Windows.
#
#   powershell -File packaging\build_web.ps1
#   (if blocked by execution policy, run the PyInstaller line below directly)
#
# Output: dist_web\BibleClipWeb\BibleClipWeb.exe (+ bible_versions, original_lang
# copied next to it). The web/ folder (HTML/CSS/JS + Pretendard fonts) is bundled
# INSIDE the exe via --add-data, resolved at runtime by config.get_resource_dir().
# pywebview ships its own PyInstaller hook, so the WebView2/pythonnet backend is
# collected automatically; no extra --collect flags needed for it.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

python -m PyInstaller --onedir --windowed --noconfirm --clean `
  --collect-submodules bibleclip `
  --hidden-import pyperclip `
  --add-data "web;web" `
  --icon=icon.ico --name BibleClipWeb `
  --distpath dist_web --workpath build_web `
  bibleclip_web.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Runtime data lives next to the exe (config.get_base_dir() = exe dir when frozen).
$dst = "dist_web\BibleClipWeb"
Copy-Item icon.ico $dst -Force
New-Item -ItemType Directory -Force "$dst\bible_versions" | Out-Null
Copy-Item bible_versions\* "$dst\bible_versions\" -Recurse -Force
New-Item -ItemType Directory -Force "$dst\original_lang" | Out-Null
Copy-Item original_lang\* "$dst\original_lang\" -Recurse -Force

Write-Host "`nBuilt: $dst\BibleClipWeb.exe" -ForegroundColor Green
