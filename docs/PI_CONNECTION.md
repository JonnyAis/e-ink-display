# Connecting to your Pi

```powershell
. .\tools\pi.ps1
$env:PI_HOST = "raspberrypi.local"   # or the Pi's IP from your router
$env:PI_USER = "pi"
Pi-Help
Pi-Find          # reachable?
Pi-SetupKey      # one time: installs your SSH key (asks for the password once)
Pi-Status        # service state, uptime, temp, recent logs
```
After `Pi-SetupKey` you can stop using the password. See `SECURITY.md`.

## Safe change workflow
1. Edit locally; preview PNGs without hardware; `python -m pytest`; commit.
2. `Pi-Deploy` - backs up, installs the committed code, restarts and watches it; rolls back by itself if it fails.
3. `Pi-Logs -Follow` to watch it; `Pi-Rollback` to put the previous version back.

Details in `DEPLOYMENT.md`. For a one-file hotfix: `Pi-Push <file>` (keeps a `.bak-<timestamp>`), then `Pi-Restart`.

Do not change Wi-Fi or systemd services remotely without a recovery path.
