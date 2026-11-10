# Connecting to your Pi

## One-time setup on each PC
1. Say where your Pi is, in `pi.env` in the project root (git-ignored, next to `config.toml`):
   ```
   PI_HOST=<pi-hostname>.local
   PI_USER=<your-pi-user>
   ```
   (`~/.config/eink/pi.env` works too; environment variables with the same names override both.)
2. Install your SSH key. You type the Pi password into ssh's own prompt, once; nothing stores it:
   ```powershell
   . .\tools\pi.ps1
   Pi-Find          # reachable?
   Pi-SetupKey      # creates ~/.ssh/id_ed25519 if needed and adds it to the Pi
   Pi-Status        # service state, uptime, temp, recent logs (no password from now on)
   ```
3. Optional: load the helpers in every PowerShell window by adding this line to `notepad $PROFILE`:
   ```powershell
   . <path-to-your-clone>\tools\pi.ps1
   ```
4. Optional: a short alias in `~/.ssh/config`, so plain `ssh eink` works:
   ```
   Host eink
       HostName <pi-hostname>.local
       User <your-pi-user>
   ```
5. Optional: reserve the Pi's IP in your router, so falling back to the IP keeps working.

To authorize another PC, repeat these steps on it. To revoke one, delete its line from `~/.ssh/authorized_keys` on the Pi.

## Safe change workflow
1. Edit locally; preview PNGs without hardware; `python -m pytest`; commit; open a PR.
2. After merging, `Pi-Ship`: checks GitHub's checks passed, moves the `live` tag, and the Pi deploys itself with
   health checks and automatic rollback (needs `Pi-InstallAutoDeploy` once; see `DEPLOYMENT.md`).
3. `Pi-Logs -Follow` to watch it; `Pi-Rollback` to put the previous version back.
4. Settings changed? `Pi-PushConfig` sends your `config.toml` (it never goes through GitHub).

For a one-file hotfix: `Pi-Push <file>` (keeps a `.bak-<timestamp>`), then `Pi-Restart`.

## Working with Claude cloud sessions
A cloud session can't reach your home network, so each kind of change has one route:

| Change | Route | Needs you? |
|---|---|---|
| Code and docs | branch + PR on GitHub | review and merge |
| Deploy to the Pi | move the `live` tag (only when you ask); the Pi pulls it within 5 minutes | ask for it |
| Your `config.toml` / `pi.env` | edits the files in your clone through folder access in the Claude app | approve the folder once |
| Send settings to the Pi, run `Pi-*` | a Remote Control session on your PC runs `Pi-PushConfig` etc. | approve the session |

Keep your settings files in the clone's root (`config.toml`, `pi.env`), so approving that one folder covers them.
The clone's `origin` must be this repo, since `Pi-Ship` moves the `live` tag on `origin`.

Do not change Wi-Fi or systemd services remotely without a recovery path.
