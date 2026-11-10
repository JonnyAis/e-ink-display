#!/usr/bin/env bash
# Runs ON THE PI, once (Pi-InstallAutoDeploy in tools/pi.ps1 copies it over and starts it).
# Installs the pull-based auto-deploy: a systemd timer that runs tools/pi_autodeploy.sh every 5 minutes.
#   pi_autodeploy_install.sh install     set up the script and timer (safe to re-run)
#   pi_autodeploy_install.sh uninstall   stop and remove the timer (keeps the app)
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/transit-display}"
SRC="$(cd "$(dirname "$0")" && pwd)"
UNIT=/etc/systemd/system/eink-autodeploy

do_install() {
    command -v git >/dev/null || { echo "Installing git"; sudo -n apt-get install -y git >/dev/null; }
    mkdir -p "$APP_DIR/tools"
    install -m 755 "$SRC/pi_autodeploy.sh" "$APP_DIR/tools/pi_autodeploy.sh"
    if [ -f "$SRC/config.toml" ]; then   # your settings, sent from your PC (never via GitHub)
        [ -f "$APP_DIR/config.toml" ] && cp "$APP_DIR/config.toml" "$APP_DIR/config.toml.bak"
        install -m 600 "$SRC/config.toml" "$APP_DIR/config.toml"
        echo "Installed your config.toml (the next deploy checks the app loads with it)."
    fi

    sudo -n tee "$UNIT.service" >/dev/null <<EOF
[Unit]
Description=E-ink display: deploy the 'live' tag from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$USER
Environment=APP_DIR=$APP_DIR
ExecStart=/bin/bash $APP_DIR/tools/pi_autodeploy.sh
EOF
    sudo -n tee "$UNIT.timer" >/dev/null <<EOF
[Unit]
Description=Check for a new 'live' tag every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
    sudo -n systemctl daemon-reload
    sudo -n systemctl enable --now eink-autodeploy.timer >/dev/null
    echo "Timer installed. The Pi checks the 'live' tag on GitHub every 5 minutes."
}

do_uninstall() {
    sudo -n systemctl disable --now eink-autodeploy.timer 2>/dev/null || true
    sudo -n rm -f "$UNIT.service" "$UNIT.timer"
    sudo -n systemctl daemon-reload
    echo "Auto-deploy removed."
}

case "${1:-}" in
    install) do_install ;;
    uninstall) do_uninstall ;;
    *) sed -n '2,5p' "$0"; exit 2 ;;
esac
