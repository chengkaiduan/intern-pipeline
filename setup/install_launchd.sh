#!/bin/zsh
# Install (or reinstall) the nightly launchd job. usage: setup/install_launchd.sh [hour] [minute]
set -euo pipefail
HOUR="${1:-4}"; MINUTE="${2:-0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.intern-pipeline"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl unload "$PLIST" 2>/dev/null || true
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-lc</string><string>"$ROOT/run.sh"</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$ROOT/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/launchd.err.log</string>
</dict>
</plist>
PL
launchctl load "$PLIST"
echo "installed $LABEL: daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), runs $ROOT/run.sh"
echo "uninstall: launchctl unload $PLIST && rm $PLIST"
