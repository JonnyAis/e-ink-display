#!/usr/bin/env bash
# Runs ON THE PI from a systemd timer (eink-autodeploy.timer). Pull-based deploys: the Pi only reaches out to GitHub,
# nothing reaches in. When the `live` tag on GitHub points at a new commit, this deploys that commit with
# tools/pi_deploy.sh (health check + automatic rollback). Merging to main alone never deploys; moving the tag does:
#     git tag -f live <commit> && git push -f origin live
#
# One-time setup is done from your PC with Pi-InstallAutoDeploy (tools/pi.ps1). The repo is private, so the Pi reads
# it with its own read-only GitHub deploy key (~/.ssh/eink_deploy); the key can't push and only sees this repo.
#
# Environment: APP_DIR (default ~/transit-display), REPO (default git@github.com:JonnyAis/e-ink-display.git),
#              TAG (default live). State lives in $APP_DIR/.autodeploy/: deployed (last good commit), failed (last
#              commit that failed; not retried until the tag moves), last-run.log.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/transit-display}"
REPO="${REPO:-git@github.com:JonnyAis/e-ink-display.git}"
TAG="${TAG:-live}"
STATE="$APP_DIR/.autodeploy"
MIRROR="$STATE/repo.git"
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/eink_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

mkdir -p "$STATE"
log() { printf '[autodeploy] %s\n' "$*"; }

if [ ! -d "$MIRROR" ]; then
    log "cloning $REPO"
    git clone --quiet --bare "$REPO" "$MIRROR"
fi
git -C "$MIRROR" fetch --quiet --force --prune origin "+refs/tags/$TAG:refs/tags/$TAG" 2>/dev/null || {
    log "no '$TAG' tag on GitHub yet (or GitHub unreachable); nothing to do"; exit 0; }

want="$(git -C "$MIRROR" rev-parse "refs/tags/$TAG^{commit}")"
have="$(cat "$STATE/deployed" 2>/dev/null || true)"
failed="$(cat "$STATE/failed" 2>/dev/null || true)"
[ "$want" = "$have" ] && exit 0
if [ "$want" = "$failed" ]; then
    log "$TAG = ${want:0:7} already failed once; waiting for the tag to move"; exit 0
fi

log "deploying ${want:0:7} ($(git -C "$MIRROR" log -1 --format=%s "$want"))"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git -C "$MIRROR" archive --format=tar.gz -o "$work/bundle.tgz" "$want" app config.example.toml
git -C "$MIRROR" show "$want:tools/pi_deploy.sh" > "$work/pi_deploy.sh"

if APP_DIR="$APP_DIR" bash "$work/pi_deploy.sh" deploy "$work/bundle.tgz" 2>&1 | tee "$STATE/last-run.log"; then
    echo "$want" > "$STATE/deployed"; rm -f "$STATE/failed"
    log "live: ${want:0:7}"
else
    echo "$want" > "$STATE/failed"
    log "deploy of ${want:0:7} failed; previous version kept (see $STATE/last-run.log)"
    exit 1
fi
