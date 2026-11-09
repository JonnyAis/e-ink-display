# Hardware & display driver

## Parts
- **Raspberry Pi Zero 2 W** (quad Cortex-A53, 512 MB, Wi-Fi/BT). Any Pi with SPI works; the Zero 2 W is the tested target.
- **IT8951-based e-paper panel** on a controller HAT, driven over SPI. The tested panel is 1872x1404 pixels
  (a Waveshare IT8951 panel). **Confirm your own panel's resolution from its label/datasheet**; don't trust a size
  quoted in a guide.
- Power: a stable 5 V supply. Brown-outs show up as failed refreshes or garbage frames.

## Enable SPI
`sudo raspi-config` -> Interface Options -> SPI -> Enable, then reboot. The service user must be in the `spi` and
`gpio` groups (the systemd unit uses `SupplementaryGroups=spi gpio`).

## The driver API (verify against your copy!)
This project uses the `IT8951` Python package (GregDMeyer/IT8951) vendored inside the app directory. The calls below
are the ones the working display uses; check your installed version before relying on them.

```python
from IT8951.display import AutoEPDDisplay
from IT8951 import constants

display = AutoEPDDisplay(vcom=-1.5, bus=0, device=0, spi_hz=24_000_000)
W, H = display.epd.width, display.epd.height          # frame buffer is mode "L" (8-bit gray)

# Full refresh: whole screen, best quality, flashes, ~2-3 s
display.frame_buf.paste(img)                           # img: PIL "L" image, exactly (W, H)
display.draw_full(constants.DisplayModes.GC16)

# Partial refresh: only a box, faster. X must be aligned to 4 pixels.
display.frame_buf.paste(patch, box=(x, y))
display.update(patch.tobytes(), (x, y), (w, h), mode)  # mode: GL16 (readable text) or A2 (fast, 1-bit)
```
- **VCOM** is printed on the panel's FPC cable label (e.g. -1.5). A wrong value gives washed-out or ghosty output.
- There is no `EPD.display()` method; don't invent one.
- **Orientation:** if your panel is mounted rotated/flipped, transform the image and any partial-update boxes
  consistently (a 180-degree flip maps box `(x0,y0,x1,y1)` to `(W-x1, H-y1, W-x0, H-y0)`). Test with a distinct
  label in each corner.

## Refresh modes
| Mode | Quality | Speed | Use |
|---|---|---|---|
| GC16 | 16 gray, clean | slowest (~2-3 s, flashes) | page changes, periodic de-ghosting scrub |
| GL16 | 16 gray, fast | faster | readable text updates |
| DU / A2 | black/white only | fastest | clocks, blinking indicators |

**Ghosting:** repeated partial updates leave faint residue. Schedule an occasional full GC16 scrub
(the reference display does one every 30 minutes) and keep A2 content strictly black/white.

## Power
`display.epd.sleep()` after a final update saves power; e-paper holds its image with no power. A display that updates
every few seconds should not sleep between updates.
