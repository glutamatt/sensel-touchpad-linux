# sensel-touchpad-linux

Configure your Sensel haptic touchpad on Linux — click force, haptic intensity, button zones.

Works on ThinkPad X1 Carbon Gen 12 and likely other laptops with Sensel touchpads (vendor `2C2F`).

## The problem

Sensel haptic touchpads have configurable click force thresholds stored in firmware, but there's no Linux tool to change them. On Windows, the Sensel UWP app handles this. On Linux, you're stuck with the factory defaults.

This tool talks directly to the touchpad firmware via its vendor-specific HID register protocol, documented through interoperability analysis.

## Quick start

```bash
sudo python3 sensel_config.py
```

No dependencies — just Python 3 and root access.

## What it does

```
  Sensel Touchpad Configuration
  Device: /dev/hidraw1
  ─────────────────────────────

  Current settings:

    Click force                          164g   (default: 164g)
    Click release threshold              108g   (default: 108g)
    Left zone click force                 76g   (default: 76g)
    Right zone click force                76g   (default: 76g)
    Middle zone click force               76g   (default: 76g)
    Haptic feedback intensity             50%   (default: 50%)
    Haptic feedback enabled                ON   (default: ON)

  What would you like to do?

    1  Show current settings
    2  Tune settings interactively
    3  Quick adjust: click force only
    4  Restore factory defaults
    5  Keep current settings across reboot/sleep
    q  Quit
```

- **Option 3** (Quick adjust) is the fastest — pick a click force in grams, release threshold auto-calculated
- **Option 2** walks through every setting with descriptions and guided input
- All values in human units (grams, percentages, on/off)
- Confirmation before every write, read-back verification after
- Factory defaults stored — restore anytime with option 4
- **Option 5** writes whatever you currently have to `/etc/sensel-touchpad.conf` so it survives reboot and sleep

## What you can tune

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| Click force | 164g | 10-500g | Main click activation force |
| Click release | 108g | 10-500g | Release threshold (hysteresis) |
| Zone forces (L/R/M) | 76g | 10-500g | Per-zone button forces |
| Zone release (L/R/M) | 50g | 10-500g | Per-zone release thresholds |
| Haptic intensity | 50% | 0-100% | Vibration feedback strength |
| Haptic enabled | ON | ON/OFF | Master haptic switch |

## Important notes

- **Changes are RAM-only** — they revert whenever the touchpad loses power: always
  on a full power-off, and on some machines across suspend or reboot too
- `install.sh` makes them stick by re-applying a saved config (see below)
- The tool auto-detects the hidraw device (scans for vendor `2C2F`)
- No dependencies beyond Python 3 stdlib

## Making changes persistent

There's no known "commit to flash" register, so settings are re-applied instead
of stored on the device:

```bash
sudo ./install.sh
```

That installs the script to `/usr/local/bin/`, a udev rule that re-applies the
config whenever a Sensel hidraw device enumerates (which is exactly when the
firmware has lost its registers — a cold boot power-cycles the touchpad), plus
a oneshot boot service and a `systemd-sleep` hook as belt-and-braces, and
offers to create `/etc/sensel-touchpad.conf` from your current settings.
`--uninstall` reverses it. To do it by hand, copy `sensel_config.py`,
`99-sensel-touchpad.rules` and the two files in `systemd/` to those paths, run
`--save-config`, then `systemctl enable sensel-touchpad.service`.

The config is `key=value` with `#` comments, keys being the `--set-` flags minus
the prefix:

```ini
click-force=76
click-release-threshold=50
haptic-feedback-intensity=35
```

```bash
sudo python3 sensel_config.py --save-config   # snapshot current settings
sudo python3 sensel_config.py --apply-config  # apply now (also what boot/resume run)
```

Both take an optional `=PATH`; otherwise it's `/etc/sensel-touchpad.conf`, then
`~/.config/sensel-touchpad.conf` (the sudo user's home, not root's). Bad keys or
out-of-range values are reported with a line number and nothing is applied.
Menu option 5 does the same as `--save-config`, and tuning offers it when you're
done, so you never have to write the file by hand.

Because the touchpad may not have enumerated when the boot service runs, and
briefly vanishes across suspend, `--apply-config` retries for up to ~5s rather
than relying on unit ordering.

## How it works

The Sensel touchpad firmware exposes a proprietary register interface over HID report ID `0x09` (vendor-defined pipe). The protocol:

1. **Write** a 3-byte read command to the HID pipe: `[cmd_high, cmd_low, size]`
2. **Read** the response: `[ACK, reg_resp, len_lo, len_hi, data..., checksum]`
3. **Write** registers with the same command format (different flag bit) + data + checksum

The command bytes encode the register address:
```
byte[0] = ((reg & 0x3F00) >> 7) | 1 | (0x80 if reading)
byte[1] = reg & 0xFF
byte[2] = data size in bytes
```

This protocol was documented through interoperability analysis of the HID interface, in accordance with EU Directive 2009/24/EC (Article 6) which permits such analysis to achieve interoperability with independently created software.

## Tested on

- ThinkPad X1 Carbon Gen 12 (21KC), Ubuntu 25.10 (kernel 6.17) — `SNSL0028:00 2C2F:0028`
- ThinkPad P1, Arch (kernel 7.1) — `SNSL002D:00 2C2F:002D`

Should work on other Sensel touchpads — the protocol is the same across models.

## License

MIT
