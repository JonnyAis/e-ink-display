# Deploying to a Pi

For connecting and day-to-day commands see `PI_CONNECTION.md`. For where secrets live see `../SECURITY.md`.

## 1. Prepare the Pi
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-dev git fonts-dejavu-core
sudo raspi-config nonint do_spi 0            # enable SPI
```
Create your own user (don't leave the default password in place) and use SSH keys; see `SECURITY.md`.

## 2. Install the app
```bash
mkdir -p ~/transit-display && cd ~/transit-display
python3 -m venv .venv
.venv/bin/pip install pillow requests python-dotenv
.venv/bin/pip install ./IT8951                # the vendored driver, not the PyPI package
# copy this repo's app/ into ~/transit-display/app/
```
Secrets go in `~/transit-display/.env` (see `.env.example`). Never commit it: `chmod 600 .env`.

## 3. Run it as a service
`/etc/systemd/system/transit-display.service` (replace `<user>`):
```ini
[Unit]
Description=E-ink display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<user>
WorkingDirectory=/home/<user>/transit-display
ExecStart=/home/<user>/transit-display/.venv/bin/python -m app.main
Restart=always
RestartSec=5
SupplementaryGroups=spi gpio

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now transit-display.service
journalctl -u transit-display.service -f
```

## 4. Updating safely
One command from your PC (PowerShell, project root, after `. .\tools\pi.ps1`):
```powershell
Pi-Deploy          # deploys the committed code at HEAD; asks first
Pi-Rollback        # puts back the version from before the last deploy
```
`Pi-Deploy` checks SSH key login, runs `Pi-Backup` to your PC, then copies `app/`, `config.example.toml` and your
personal `config.toml` (if you have one; otherwise the Pi keeps its own). On the Pi, `tools/pi_deploy.sh` then:
1. compiles the new code and loads it with the config (needs `[bus] stops`); if that fails, nothing changes;
2. saves the current `app/` and config files to `~/transit-display/.deploy-backups/<time>/` (last 5 kept);
3. swaps in the new version and restarts the service (`sudo` must work without a password, as on a stock Pi);
4. watches it for 45 s: if it stops, crash-loops or logs a traceback, it restores the backup and restarts.

It never touches `.env`, `.venv`, `assets/` (licensed fonts, logo), logs or the display driver. Only committed code
is deployed. On Python < 3.11 it installs `tomli` into the venv.

### Deploying without your PC (the `live` tag)
Run `Pi-InstallAutoDeploy` once. It copies your `config.toml` to the Pi and installs a timer that checks GitHub every
5 minutes. The repo is public, so the Pi reads it over HTTPS with no key or token (for a private fork, set `REPO` to
its `git@` URL and put a read-only deploy key at `~/.ssh/eink_deploy` on the Pi). From then on, moving the `live` tag
deploys, from anywhere, with the same checks and automatic rollback:
```bash
git tag -f live origin/main && git push -f origin live
```
Merging to `main` never deploys by itself. The Pi only connects out to GitHub; nothing on your network is opened.
A commit that fails is not retried until the tag moves again. Logs: `journalctl -u eink-autodeploy`; state in
`~/transit-display/.autodeploy/`. Remove it with `pi_autodeploy_install.sh uninstall` on the Pi.

### The everyday deploy: `Pi-Ship`
After merging to `main`, run `Pi-Ship` (from `tools/pi.ps1`). It confirms GitHub's checks passed on that exact commit,
moves the `live` tag, starts the deploy if the Pi is reachable, and tells you whether the commit went live or the Pi
rolled back. Away from home it just moves the tag, and the Pi deploys within 5 minutes.

### Your settings
Your `config.toml` (team, bus stops, rotation) and `.env` live only on your PC and the Pi, never on GitHub. Deploys keep
the Pi's copy. After changing settings locally, `Pi-PushConfig` sends them, checks the app loads with them, restarts,
and restores the old file if the display doesn't stay up.

For a one-file hotfix, `Pi-Push <file>` still works (it leaves a `.bak-<timestamp>` of the remote file).

## 5. Wi-Fi onboarding (optional, for devices that move networks)
Pattern: at boot, if there is no Wi-Fi + internet, start an access point and a small web portal where the new owner
enters their Wi-Fi details; then reboot into normal mode (NetworkManager `nmcli` does the switching).

**Security requirements for this pattern:**
- Generate a **random hotspot password per device** (e.g. printed on the welcome screen/label). Never ship one shared
  default; anyone who knows it can join every unit's setup network.
- The portal accepts a Wi-Fi password, so serve it only on the hotspot and shut it down once the device is online.
- Don't expose it (or SSH) to the internet.

## 6. Preparing a device to give away
Do this deliberately; the usual one-liner deletes **every** saved Wi-Fi profile and can strand you.
1. Back up what you want to keep (`Pi-Backup`).
2. Remove your SSH keys from `~/.ssh/authorized_keys`, and set a new password (give it to the recipient securely).
3. Remove your API keys from `.env` (the recipient should use their own).
4. Remove saved Wi-Fi profiles: `nmcli -t -f NAME,TYPE connection show`, then `sudo nmcli connection delete "<name>"`
   for each Wi-Fi profile except the setup hotspot.
5. Keep a way back in: only do step 4 when you can reach the Pi's hotspot or have console access.
6. Reboot and confirm it comes up in setup mode.
