<#
  Helpers for the e-ink transit display Pi.
  Usage (PowerShell, from the project root):
      . .\tools\pi.ps1
      Pi-Help

  Your Pi's address goes in ~/.config/eink/pi.env, outside the repo, one setting per line:
      PI_HOST=<pi-hostname-or-ip>
      PI_USER=<pi-user>
  Environment variables with the same names override that file.
  No password is stored here. Run Pi-SetupKey once, then everything is passwordless.
#>

$script:PiSettings = @{}
$script:PiSettingsFile = Join-Path $HOME ".config\eink\pi.env"
if (Test-Path $script:PiSettingsFile) {
    foreach ($line in Get-Content $script:PiSettingsFile) {
        if ($line -match '^\s*(PI_[A-Z]+)\s*=\s*(.+?)\s*$') { $script:PiSettings[$Matches[1]] = $Matches[2] }
    }
}
function Get-PiSetting([string]$Name, [string]$Default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { $fromEnv } elseif ($script:PiSettings[$Name]) { $script:PiSettings[$Name] } else { $Default }
}

$script:PiUser = Get-PiSetting "PI_USER" "pi"
$script:PiHostName = Get-PiSetting "PI_HOST" "raspberrypi.local"
$script:PiApp = Get-PiSetting "PI_APP" "/home/$script:PiUser/transit-display"
$script:GitHubRepo = "JonnyAis/e-ink-display"
$script:PiService = "transit-display.service"
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:SshOpts = @("-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new")

function Pi-Target { "$script:PiUser@$script:PiHostName" }

function Pi-Help {
    @"
Pi-Find            Check the Pi is reachable (DNS, ping, SSH port)
Pi-SavePassword    Store the Pi password encrypted (Windows DPAPI) in your user profile
Pi-SetupKey        One-time: create an SSH key and install it on the Pi (asks for the password once)
Pi-Ssh             Open an interactive shell on the Pi
Pi-Run <cmd>       Run one command on the Pi and print the output
Pi-Status          Service state, uptime, temperature, last log lines
Pi-Logs [-Follow]  Show (or follow) the transit-display journal
Pi-Restart         Restart transit-display.service (asks first)
Pi-Backup          Download app code (no .venv/.env/logs) to pi-backup\<timestamp>
Pi-Push <file>     Copy a local file to the app dir (backs up the remote file first)
Pi-Deploy          Install the committed app on the Pi: backup, check, restart, verify, auto-rollback
Pi-Rollback        Put back the version from before the last Pi-Deploy and restart
Pi-PushConfig      Copy your local config.toml to the Pi and restart (old one comes back if it won't load)
Pi-InstallAutoDeploy  One-time: let the Pi deploy itself whenever the 'live' tag moves on GitHub
Pi-Ship            Deploy what's on GitHub main: confirm its checks passed, move 'live', report the result
Pi-SyncPrivacyTerms  Update the GitHub secret that CI uses to scan for your personal values
"@
}

function Pi-Ship {
    <#
      The everyday deploy. Ships origin/main (or -Ref <commit>) if GitHub's checks passed on that exact commit.
      On your home network it starts the deploy now and reports the result. Away from home, the Pi picks it up
      within 5 minutes by itself.
        Pi-Ship          # asks first
        Pi-Ship -Yes
    #>
    param([string]$Ref = "origin/main", [switch]$Yes)
    Push-Location $script:ProjectRoot
    try {
        git fetch --quiet origin
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not reach GitHub."; return }
        $sha = (git rev-parse "$Ref^{commit}").Trim()
        if ($LASTEXITCODE -ne 0) { Write-Warning "Unknown git ref '$Ref'."; return }
        $short = $sha.Substring(0, 7)

        $runs = @(gh api "repos/$script:GitHubRepo/commits/$sha/check-runs" --jq '.check_runs[] | "\(.name) \(.status) \(.conclusion)"')
        if ($LASTEXITCODE -ne 0 -or $runs.Count -eq 0) { Write-Warning "No checks found for $short. Not shipping."; return }
        $notGood = @($runs | Where-Object { $_ -notmatch ' completed (success|skipped)$' })
        if ($notGood.Count) {
            Write-Warning "Checks haven't all passed on $short, so it was not shipped:"
            $notGood | ForEach-Object { Write-Host "  $_" }
            return
        }

        $current = ((git ls-remote origin "refs/tags/live^{}" "refs/tags/live") | Select-Object -First 1)
        if ($current -and $current.StartsWith($sha)) { Write-Host "$short is already the live version."; return }
        Write-Host "Ship $short ($((git log -1 --format=%s $sha).Trim()))"
        if (-not $Yes -and (Read-Host "Continue? (y/N)") -ne "y") { return }

        git tag -f live $sha | Out-Null
        git push --quiet -f origin live
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not move the live tag."; return }

        ssh @script:SshOpts -o BatchMode=yes (Pi-Target) "true" 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Host "Tag moved. The Pi isn't reachable from here, so it will deploy $short within 5 minutes."; return }

        Write-Host "Deploying on the Pi (about a minute)..."
        Pi-Run "sudo -n systemctl start eink-autodeploy.service" 2>$null
        $deployed = (Pi-Run "cat $script:PiApp/.autodeploy/deployed 2>/dev/null")
        if ($deployed -and $deployed.Trim() -eq $sha) {
            Write-Host "OK: $short is live on the display."
        } else {
            Write-Warning "$short did not go live; the Pi kept its previous version. What it reported:"
            Pi-Run "tail -n 30 $script:PiApp/.autodeploy/last-run.log 2>/dev/null; journalctl -u eink-autodeploy -n 15 --no-pager"
        }
    } finally {
        Pop-Location
    }
}

function Pi-SyncPrivacyTerms {
    # Copies the values in your config.toml and .env into an encrypted GitHub secret. Run it after changing them.
    Push-Location $script:ProjectRoot
    try {
        python tools\check_personal.py --dump-terms | gh secret set PERSONAL_TERMS --repo $script:GitHubRepo
        if ($LASTEXITCODE -eq 0) { Write-Host "PERSONAL_TERMS updated." } else { Write-Warning "Could not update the secret." }
    } finally {
        Pop-Location
    }
}

function Pi-Find {
    $r = Test-NetConnection $script:PiHostName -Port 22 -WarningAction SilentlyContinue
    if ($r.TcpTestSucceeded) {
        Write-Host "OK: $script:PiHostName -> $($r.RemoteAddress), SSH port open"
    } else {
        Write-Warning "Cannot reach $script:PiHostName on port 22. Try: `$env:PI_HOST = '<ip from your router>'"
        Write-Host "Find the Pi's IP in your router. Not on the same Wi-Fi? Join it first."
    }
}

$script:CredFile = Join-Path $HOME ".eink-pi.cred"   # DPAPI-encrypted, per Windows user, outside the repo

function Pi-SavePassword {
    # Prompts for the password and stores it encrypted (only this Windows account on this PC can decrypt it).
    Read-Host "Pi password for $(Pi-Target)" -AsSecureString | Export-Clixml $script:CredFile
    Write-Host "Saved to $script:CredFile (encrypted)."
}

function Pi-SetupKey {
    $key = Join-Path $HOME ".ssh\id_ed25519"
    if (-not (Test-Path $key)) {
        New-Item -ItemType Directory -Force (Split-Path $key) | Out-Null
        ssh-keygen -t ed25519 -f $key -N '""' -C "$env:USERNAME@$env:COMPUTERNAME-eink"
    }
    $remote = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    $askpass = $null
    if (Test-Path $script:CredFile) {
        # Feed the saved password to ssh via a temp askpass script that is deleted right after.
        $plain = [System.Net.NetworkCredential]::new("", (Import-Clixml $script:CredFile)).Password
        $askpass = Join-Path $env:TEMP "pi-askpass.cmd"
        Set-Content $askpass "@echo off`r`necho $plain" -Encoding ascii
        $env:SSH_ASKPASS = $askpass; $env:SSH_ASKPASS_REQUIRE = "force"
    } else {
        Write-Host "No saved password; enter the Pi password when prompted (or run Pi-SavePassword first)."
    }
    try {
        Get-Content "$key.pub" | ssh @script:SshOpts (Pi-Target) $remote
    } finally {
        if ($askpass) { Remove-Item $askpass -Force -ErrorAction SilentlyContinue }
        Remove-Item Env:SSH_ASKPASS, Env:SSH_ASKPASS_REQUIRE -ErrorAction SilentlyContinue
    }
    Write-Host "Done. Test with: Pi-Run hostname"
}

function Pi-Ssh { ssh @script:SshOpts (Pi-Target) }

function Pi-Run {
    param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Command)
    ssh @script:SshOpts -o BatchMode=yes (Pi-Target) ($Command -join " ")
}

function Pi-Status {
    Pi-Run "hostname; uptime -p; vcgencmd measure_temp 2>/dev/null; systemctl is-active $script:PiService wifi-mode-manager.service; journalctl -u $script:PiService -n 8 --no-pager"
}

function Pi-Logs {
    param([switch]$Follow, [int]$Lines = 50)
    $f = if ($Follow) { "-f" } else { "" }
    ssh @script:SshOpts (Pi-Target) "journalctl -u $script:PiService -n $Lines $f --no-pager"
}

function Pi-Restart {
    if ((Read-Host "Restart $script:PiService? (y/N)") -ne "y") { return }
    Pi-Run "sudo systemctl restart $script:PiService; sleep 2; systemctl is-active $script:PiService"
}

function Pi-Backup {
    $dest = Join-Path $script:ProjectRoot ("pi-backup\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    New-Item -ItemType Directory -Force $dest | Out-Null
    $tgz = Join-Path $dest "transit-display.tgz"
    # cmd /c keeps the binary stream intact (PowerShell's > would corrupt it)
    cmd /c "ssh -o BatchMode=yes $(Pi-Target) `"cd $script:PiApp && tar czf - --exclude=.venv --exclude=__pycache__ --exclude=logs --exclude=.env .`" > `"$tgz`""
    tar xzf $tgz -C $dest
    Write-Host "Backed up to $dest"
}

function Pi-Push {
    param([Parameter(Mandatory)][string]$LocalFile, [string]$RemotePath)
    if (-not $RemotePath) { $RemotePath = "$script:PiApp/app/" + (Split-Path $LocalFile -Leaf) }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Pi-Run "[ -f $RemotePath ] && cp $RemotePath $RemotePath.bak-$stamp; true"
    scp @script:SshOpts $LocalFile "$(Pi-Target):$RemotePath"
    Write-Host "Pushed. Restart the service with Pi-Restart to apply."
}

function Pi-PersonalConfig {
    # Same lookup order as app/config.py. Returns $null when you have no personal config.
    $candidates = @()
    if ($env:EINK_CONFIG) { $candidates += $env:EINK_CONFIG }
    $candidates += (Join-Path $script:ProjectRoot "config.toml"), (Join-Path $HOME ".config\eink\config.toml")
    $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Pi-Deploy {
    <#
      Deploys the committed app/ (not uncommitted edits) to the Pi in one step:
        1. checks SSH key login, 2. Pi-Backup to your PC, 3. copies app/ + config.example.toml (+ your config.toml),
        4. on the Pi: syntax + config check, backup, swap, restart, then watches the service for 45 s.
      If the new version doesn't stay up, the Pi puts the previous version back by itself.
      Never touches .env, .venv, assets/ (licensed fonts, logo) or logs on the Pi.
        Pi-Deploy              # deploy HEAD, asks first
        Pi-Deploy -Ref main -Yes
    #>
    param([string]$Ref = "HEAD", [switch]$Yes)
    Push-Location $script:ProjectRoot
    $bundle = $null
    try {
        ssh @script:SshOpts -o BatchMode=yes (Pi-Target) "true" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Can't log in to $(Pi-Target) with an SSH key. Run Pi-Find, then Pi-SetupKey (once)."
            return
        }
        $sha = (git rev-parse --short $Ref).Trim()
        if (-not $sha) { Write-Warning "Unknown git ref '$Ref'."; return }
        if (git status --porcelain -- app config.example.toml) {
            Write-Warning "You have uncommitted changes in app/. Only committed code is deployed ($Ref = $sha)."
        }
        $cfg = Pi-PersonalConfig
        $cfgNote = if ($cfg) { "your $cfg" } else { "the Pi's existing config.toml" }
        Write-Host "Deploy $sha ($((git log -1 --format=%s $Ref).Trim())) to $(Pi-Target) using $cfgNote."
        if (-not $Yes -and (Read-Host "Continue? (y/N)") -ne "y") { return }

        Pi-Backup
        $bundle = Join-Path $env:TEMP "eink-deploy-$sha.tgz"
        git archive --format=tar.gz -o $bundle $Ref app config.example.toml
        if ($LASTEXITCODE -ne 0) { Write-Warning "git archive failed."; return }

        $remote = "/tmp/eink-deploy"
        Pi-Run "rm -rf $remote && mkdir -p $remote" | Out-Null
        scp @script:SshOpts -q $bundle "$(Pi-Target):$remote/bundle.tgz"
        scp @script:SshOpts -q (Join-Path $PSScriptRoot "pi_deploy.sh") "$(Pi-Target):$remote/pi_deploy.sh"
        $cfgArg = ""
        if ($cfg) { scp @script:SshOpts -q $cfg "$(Pi-Target):$remote/config.toml"; $cfgArg = "$remote/config.toml" }

        ssh @script:SshOpts -o BatchMode=yes (Pi-Target) `
            "APP_DIR=$script:PiApp SERVICE=$script:PiService bash $remote/pi_deploy.sh deploy $remote/bundle.tgz $cfgArg; rc=`$?; rm -rf $remote; exit `$rc"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Deployed $sha. Watch it with: Pi-Logs -Follow"
        } else {
            Write-Warning "Deploy of $sha did not go live (see the [deploy] lines above). The Pi is on its previous version."
        }
    } finally {
        if ($bundle) { Remove-Item $bundle -Force -ErrorAction SilentlyContinue }
        Pop-Location
    }
}

function Pi-Rollback {
    # Restores the version saved by the most recent Pi-Deploy (kept on the Pi in .deploy-backups/) and restarts.
    if ((Read-Host "Roll $(Pi-Target) back to the version before the last deploy? (y/N)") -ne "y") { return }
    $remote = "/tmp/eink-deploy"
    Pi-Run "mkdir -p $remote" | Out-Null
    scp @script:SshOpts -q (Join-Path $PSScriptRoot "pi_deploy.sh") "$(Pi-Target):$remote/pi_deploy.sh"
    ssh @script:SshOpts -o BatchMode=yes (Pi-Target) `
        "APP_DIR=$script:PiApp SERVICE=$script:PiService bash $remote/pi_deploy.sh rollback; rc=`$?; rm -rf $remote; exit `$rc"
}

function Pi-ShipTools {
    # Copies the Pi-side scripts to /tmp/eink-deploy on the Pi; returns that path.
    $remote = "/tmp/eink-deploy"
    Pi-Run "rm -rf $remote && mkdir -p $remote" | Out-Null
    foreach ($f in "pi_deploy.sh", "pi_autodeploy.sh", "pi_autodeploy_install.sh") {
        scp @script:SshOpts -q (Join-Path $PSScriptRoot $f) "$(Pi-Target):$remote/$f"
    }
    $remote
}

function Pi-PushConfig {
    # Your settings (team, bus stops, rotation) live only on the Pi and your PC, never on GitHub.
    # This copies your local config.toml to the Pi, checks the app loads with it, restarts, and puts the
    # old file back by itself if the display doesn't stay up.
    $cfg = Pi-PersonalConfig
    if (-not $cfg) { Write-Warning "No personal config.toml found (see docs/CONFIG.md)."; return }
    if ((Read-Host "Send $cfg to $(Pi-Target) and restart the display? (y/N)") -ne "y") { return }
    $remote = Pi-ShipTools
    scp @script:SshOpts -q $cfg "$(Pi-Target):$remote/config.toml"
    ssh @script:SshOpts -o BatchMode=yes (Pi-Target) `
        "APP_DIR=$script:PiApp SERVICE=$script:PiService bash $remote/pi_deploy.sh config $remote/config.toml; rc=`$?; rm -rf $remote; exit `$rc"
}

function Pi-InstallAutoDeploy {
    <#
      One-time setup so deploys can be started from anywhere (including Claude in the cloud) without any access to
      your network: every 5 minutes the Pi checks the 'live' tag on GitHub and, if it moved, deploys that commit with
      the same checks and automatic rollback as Pi-Deploy. Merging to main never deploys by itself.
      Also copies your config.toml to the Pi (settings never go through GitHub).
      Afterwards add the printed key to GitHub as a read-only deploy key (the repo is private).
    #>
    ssh @script:SshOpts -o BatchMode=yes (Pi-Target) "true" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Can't log in to $(Pi-Target) with an SSH key. Run Pi-SetupKey first."; return }
    $remote = Pi-ShipTools
    $cfg = Pi-PersonalConfig
    if ($cfg) { scp @script:SshOpts -q $cfg "$(Pi-Target):$remote/config.toml" }
    else { Write-Host "No local config.toml; the Pi keeps the one it has." }
    ssh @script:SshOpts -o BatchMode=yes (Pi-Target) `
        "APP_DIR=$script:PiApp bash $remote/pi_autodeploy_install.sh install; rc=`$?; rm -rf $remote; exit `$rc"
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Last step: add the key above at https://github.com/JonnyAis/e-ink-display/settings/keys/new"
        Write-Host "(title 'e-ink Pi', leave 'Allow write access' unticked). Deploy by moving the tag:"
        Write-Host "    git tag -f live origin/main; git push -f origin live"
        Write-Host "Check on it with: Pi-Run journalctl -u eink-autodeploy -n 30 --no-pager"
    }
}
