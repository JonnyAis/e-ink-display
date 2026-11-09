# Troubleshooting

Start with: `Pi-Status` (service state, temperature, recent logs) and `Pi-Logs -Follow`.

## Display
| Symptom | Check |
|---|---|
| Blank / never initializes | SPI enabled? User in `spi`,`gpio` groups? Ribbon/HAT seated? Try a lower `spi_hz`. |
| Washed-out or ghosty image | VCOM value (from the panel's cable label). Run a full GC16 refresh. |
| Garbage / shifted pixels | Image size must equal the panel exactly; mode `L`. Partial-update X must be 4-aligned. |
| Text smeared after many updates | Ghosting: add a periodic full GC16 scrub. Keep A2 content strictly black/white. |
| Page upside down / mirrored | Flip the image and the partial-update boxes consistently; test with corner labels. |
| Slow refresh | Full refresh takes ~2-3 s by design; use partial updates for small changes. |

## Service
- `systemctl status transit-display.service`, `journalctl -u transit-display.service -n 100`.
- Restart loop: `systemctl show transit-display.service -p NRestarts`; read the traceback in the journal.
- After editing Python on the Pi: `.venv/bin/python -m py_compile app/*.py` before restarting.

## Network / APIs
- Can't reach the Pi: same Wi-Fi? Try the IP from your router instead of `.local`. `Pi-Find` checks DNS, ping and port 22.
- API failing: check the key in `.env`, `ping 8.8.8.8` from the Pi, provider rate limits, and the journal.
- A page says STALE: the provider or network is failing and cached data is being shown.

## Wi-Fi onboarding
- Not entering setup mode: `journalctl -u wifi-mode-manager.service`; `nmcli connection show` (is the hotspot profile present?);
  `systemctl status NetworkManager`.
- Portal unreachable: is the portal service running (it should only run in setup mode)? Are you on the hotspot, not your home Wi-Fi?

## Locked out of SSH
Don't reimage. Join the Pi's hotspot if it has one, use a monitor/keyboard, or edit `authorized_keys`/`sshd_config`
on the SD card from another computer. Keep a second way in before changing SSH settings.
