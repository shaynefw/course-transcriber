#!/bin/bash
# Builds Transcriber.app (the double-clickable launcher, with its icon) next to this script.
# Run it once after cloning. Safe to re-run any time (e.g. if the icon looks wrong).
cd "$(dirname "$0")" || exit 1
OUT="${1:-Transcriber.app}"
rm -rf "$OUT"
osacompile -o "$OUT" <<'APPLESCRIPT' || { echo "osacompile failed"; exit 1; }
-- Double-clicking the app starts the panel (and opens it in your browser).
on run
	my startPanel("")
end run

-- A transcriber:// link (the "Reopen Transcriber" button on the closed page) starts the panel quietly:
-- the page that sent the link is still open and reconnects by itself, so no second tab is opened.
on open location theURL
	my startPanel("TRANSCRIBER_NO_BROWSER=1 ")
end open location

on startPanel(envPrefix)
	set appPath to POSIX path of (path to me)
	set appDir to do shell script "dirname " & quoted form of appPath
	do shell script envPrefix & "nohup " & quoted form of (appDir & "/gui.command") & " >/dev/null 2>&1 &"
end startPanel
APPLESCRIPT
# register the transcriber:// link type with macOS
/usr/libexec/PlistBuddy \
  -c "Add :CFBundleURLTypes array" \
  -c "Add :CFBundleURLTypes:0 dict" \
  -c "Add :CFBundleURLTypes:0:CFBundleURLName string Transcriber" \
  -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" \
  -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string transcriber" "$OUT/Contents/Info.plist" >/dev/null
cp assets/Transcriber.icns "$OUT/Contents/Resources/applet.icns"
rm -f "$OUT/Contents/Resources/Assets.car"
codesign --force --deep -s - "$OUT" 2>/dev/null
touch "$OUT"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$OUT" 2>/dev/null
echo "Built $OUT. Double-click it to open the Transcriber panel."
echo "(If Finder still shows a plain icon, run:  killall Finder Dock)"
