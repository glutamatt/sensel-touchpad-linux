#!/bin/bash
# Install sensel_config.py plus the boot service and resume hook that re-apply
# your settings (firmware writes are RAM-only).
#
#   sudo ./install.sh              install
#   sudo ./install.sh --uninstall  remove, keeping the config file

set -euo pipefail

CONFIG=/etc/sensel-touchpad.conf
SCRIPT=/usr/local/bin/sensel_config.py
UNIT=/etc/systemd/system/sensel-touchpad.service
HOOK=/usr/lib/systemd/system-sleep/sensel-touchpad
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [[ $EUID -ne 0 ]]; then
	echo "Needs root. Run: sudo $0" >&2
	exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
	systemctl disable --now sensel-touchpad.service 2>/dev/null || true
	rm -f "$SCRIPT" "$UNIT" "$HOOK"
	systemctl daemon-reload
	echo "Removed. Config left at $CONFIG"
	exit 0
fi

install -Dm755 "$SRC/sensel_config.py" "$SCRIPT"
install -Dm644 "$SRC/systemd/sensel-touchpad.service" "$UNIT"
install -Dm755 "$SRC/systemd/sensel-touchpad-sleep" "$HOOK"
systemctl daemon-reload
systemctl enable sensel-touchpad.service >/dev/null

echo "Installed $SCRIPT, $UNIT, $HOOK"

if [[ -f $CONFIG ]]; then
	echo "Using existing $CONFIG"
	exit 0
fi

later="Create it later with: sudo sensel_config.py --save-config"

# Not a terminal (piped, or run from a script): don't block on a prompt.
if [[ ! -t 0 ]]; then
	echo "No $CONFIG yet. $later"
	exit 0
fi

read -r -p "Create $CONFIG from current touchpad settings? [y/N] " answer
if [[ ${answer,,} != y ]]; then
	echo "Skipped — nothing is restored until $CONFIG exists. $later"
elif ! "$SCRIPT" --save-config; then
	echo "Could not read the touchpad, so $CONFIG was not created. $later"
fi
