#!/usr/bin/env bash
# Runs ON THE PI. Installs a release bundle with a health check and automatic rollback.
# Normally started by Pi-Deploy / Pi-Rollback in tools/pi.ps1; you rarely run it by hand.
#
#   pi_deploy.sh deploy   <bundle.tgz> [config.toml]   install the bundle, restart, verify, roll back on failure
#   pi_deploy.sh config   <config.toml>              install new settings for the current app (same checks/rollback)
#   pi_deploy.sh rollback                              restore the most recent backup and restart
#   pi_deploy.sh check                                 is the service healthy right now?
#
# Environment: APP_DIR (default ~/transit-display), SERVICE (default transit-display.service),
#              SETTLE_SECS (default 45: how long the new version must run cleanly), KEEP (backups kept, default 5).
# Never touches .env, .venv, assets/ (licensed fonts, logo), logs or the display driver.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/transit-display}"
SERVICE="${SERVICE:-transit-display.service}"
SETTLE_SECS="${SETTLE_SECS:-45}"
KEEP="${KEEP:-5}"
PY="$APP_DIR/.venv/bin/python"
BACKUPS="$APP_DIR/.deploy-backups"
STAGE="$APP_DIR/.deploy-staging"
MANAGED=(app config.example.toml config.toml)   # everything a deploy may replace, relative to APP_DIR

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

restarts() { systemctl show "$SERVICE" -p NRestarts --value 2>/dev/null || echo 0; }

restart_and_verify() {
    local before since
    since="$(date '+%Y-%m-%d %H:%M:%S')"
    if ! sudo -n systemctl restart "$SERVICE"; then log "could not restart $SERVICE"; return 1; fi
    before="$(restarts)"
    log "restarted; watching for ${SETTLE_SECS}s"
    sleep "$SETTLE_SECS"
    if ! systemctl is-active --quiet "$SERVICE"; then
        log "service is not active"; return 1
    fi
    if [ "$(restarts)" != "$before" ]; then
        log "service restarted itself (crash loop)"; return 1
    fi
    if journalctl -u "$SERVICE" --since "$since" --no-pager 2>/dev/null | grep -q "Traceback"; then
        log "traceback in the log since restart:"
        journalctl -u "$SERVICE" --since "$since" --no-pager | grep -A12 "Traceback" | tail -n 20
        return 1
    fi
    return 0
}

snapshot() {   # copy the live managed files into a new backup dir; prints its path
    local dest="$BACKUPS/$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$dest"
    for f in "${MANAGED[@]}"; do
        if [ -e "$APP_DIR/$f" ]; then cp -a "$APP_DIR/$f" "$dest/"; fi
    done
    echo "$dest"
}

restore() {    # put a backup dir's files back in place
    local src="$1"
    for f in "${MANAGED[@]}"; do
        rm -rf "${APP_DIR:?}/$f"
        if [ -e "$src/$f" ]; then cp -a "$src/$f" "$APP_DIR/"; fi
    done
}

prune() {
    [ -d "$BACKUPS" ] || return 0
    ls -1d "$BACKUPS"/*/ 2>/dev/null | sort | head -n -"$KEEP" | xargs -r rm -rf
}

validate() {   # compile + load the app in $1 with the config.toml in $1; dies (nothing changed) on failure
    local dir="$1"
    log "checking the new code"
    find "$dir/app" -name '*.py' -print0 | xargs -0 "$PY" -m py_compile || die "syntax error; nothing changed"
    (cd "$dir" && EINK_CONFIG= "$PY" -c "
from app import config, rotation
stops = config.get('bus.stops') or []
import sys
if len(stops) < 2: sys.exit('[deploy] config.toml needs [bus] stops = [\"<stop id>\", \"<stop id>\"]')
pages = [p.name for p in rotation.from_config().pages]
print('[deploy] config ok: %d bus stops, rotating %s' % (len(stops), ', '.join(pages)))
") || die "the new version does not load with this config; nothing changed"

}

deploy() {
    local bundle="${1:-}" cfg="${2:-}"
    [ -f "$bundle" ] || die "bundle not found: $bundle"
    [ -x "$PY" ] || die "no virtualenv at $APP_DIR/.venv (see docs/DEPLOYMENT.md)"
    sudo -n true 2>/dev/null || die "sudo needs a password for this user, so the service can't be restarted unattended; nothing changed"

    log "staging $bundle"
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    tar xzf "$bundle" -C "$STAGE"
    [ -d "$STAGE/app" ] || die "bundle has no app/ folder"
    if [ -n "$cfg" ]; then
        cp "$cfg" "$STAGE/config.toml"
    elif [ -f "$APP_DIR/config.toml" ]; then
        cp "$APP_DIR/config.toml" "$STAGE/config.toml"      # keep the Pi's own settings
    fi

    if ! "$PY" -c "import tomllib" 2>/dev/null && ! "$PY" -c "import tomli" 2>/dev/null; then
        log "installing tomli (Python < 3.11)"
        "$PY" -m pip install --quiet tomli || die "could not install tomli"
    fi

    validate "$STAGE"

    local backup; backup="$(snapshot)"
    log "backed up current version to $backup"
    for f in "${MANAGED[@]}"; do
        if [ -e "$STAGE/$f" ]; then rm -rf "${APP_DIR:?}/$f"; mv "$STAGE/$f" "$APP_DIR/"; fi
    done
    rm -rf "$STAGE"

    if restart_and_verify; then
        prune
        log "OK: new version is running"
    else
        log "rolling back to $backup"
        restore "$backup"
        restart_and_verify && log "rolled back; the previous version is running again" \
            || log "WARNING: the previous version is not healthy either; check Pi-Logs"
        exit 1
    fi
}

set_config() {   # install a new config.toml for the current app; restores the old one if the display won't run
    local cfg="${1:-}"
    [ -f "$cfg" ] || die "config file not found: $cfg"
    [ -d "$APP_DIR/app" ] || die "no app installed in $APP_DIR"
    sudo -n true 2>/dev/null || die "sudo needs a password for this user; nothing changed"
    rm -rf "$STAGE"; mkdir -p "$STAGE"
    cp -a "$APP_DIR/app" "$STAGE/"
    [ -f "$APP_DIR/config.example.toml" ] && cp "$APP_DIR/config.example.toml" "$STAGE/"
    cp "$cfg" "$STAGE/config.toml"
    validate "$STAGE"
    local backup; backup="$(snapshot)"
    install -m 600 "$cfg" "$APP_DIR/config.toml"
    rm -rf "$STAGE"
    if restart_and_verify; then
        prune; log "OK: new settings are live"
    else
        log "restoring the previous settings"; restore "$backup"
        restart_and_verify || log "WARNING: the display is not healthy with the old settings either; check Pi-Logs"
        exit 1
    fi
}

rollback() {
    local last; last="$(ls -1d "$BACKUPS"/*/ 2>/dev/null | sort | tail -n 1 || true)"; last="${last%/}"
    [ -n "$last" ] || die "no backups in $BACKUPS"
    log "restoring $last"
    restore "$last"
    restart_and_verify && log "OK: restored version is running" || die "restored version is not healthy; check Pi-Logs"
}

case "${1:-}" in
    deploy)   shift; deploy "$@" ;;
    config)   shift; set_config "$@" ;;
    rollback) rollback ;;
    check)    systemctl is-active "$SERVICE"; echo "NRestarts=$(restarts)" ;;
    *)        sed -n '2,13p' "$0"; exit 2 ;;
esac
