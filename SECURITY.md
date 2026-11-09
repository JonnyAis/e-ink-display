# Security & credentials

Where each secret lives. **None of them belong in this repository.**

| Secret | Lives in | Notes |
|---|---|---|
| Pi login password | Your password manager | Change the default. Prefer SSH keys, then disable password SSH. |
| SSH private key | `~/.ssh/` on your PC | Never commit; `.gitignore` blocks `id_*` and `*.pem`. |
| Saved password (optional) | `%USERPROFILE%\.eink-pi.cred` | Encrypted with Windows DPAPI; only your Windows account can read it. |
| API keys (e.g. OneBusAway) | `.env` on the Pi | Copy `.env.example`; `.env` is git-ignored. |
| Personal settings (team, stops, names) | `config.toml` (git-ignored) | Not secret, but not shared. See `docs/CONFIG.md`. |
| Wi-Fi password | The device's NetworkManager | Entered via the setup portal; never in code. |
| Setup-hotspot password | Generate one per device | Do not ship a shared default. |

## Before you commit
- `git status` and `git diff --cached` - read what you're about to publish.
- Enable GitHub **push protection** (Settings -> Code security) and consider `gitleaks` as a pre-commit hook.
- If a secret is ever committed, rotate it immediately; deleting the file does not remove it from history.

## Reporting
Open a private security advisory on the repository.
