#!/usr/bin/env bash
# Install the bi-weekly audit launchd job.
# Run: bash scripts/install_audit_job.sh
#
# Uninstall: launchctl unload ~/Library/LaunchAgents/com.dustin.marketing-cli.biweekly-audit.plist
set -euo pipefail

PLIST_SRC="/Users/dustinsinger/marketing-cli/scripts/com.dustin.marketing-cli.biweekly-audit.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.dustin.marketing-cli.biweekly-audit.plist"

[[ -f "$PLIST_SRC" ]] || { echo "Missing plist: $PLIST_SRC"; exit 1; }

mkdir -p ~/marketing-cli/audits/_data
mkdir -p ~/Library/LaunchAgents
cp "$PLIST_SRC" "$PLIST_DEST"

# Unload if already loaded, then load fresh
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✅ Loaded launchd job: com.dustin.marketing-cli.biweekly-audit"
echo "   Fires every Sunday at 06:00 (see plist; bi-weekly throttling TBD)"
echo "   Logs: ~/marketing-cli/audits/_data/launchd.{stdout,stderr}.log"
echo ""
echo "To test now (without waiting for schedule):"
echo "   launchctl start com.dustin.marketing-cli.biweekly-audit"
echo ""
echo "To uninstall:"
echo "   launchctl unload $PLIST_DEST && rm $PLIST_DEST"
