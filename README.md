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
    q  Quit
```

- **Option 3** (Quick adjust) is the fastest — pick a click force in grams, release threshold auto-calculated
- **Option 2** walks through every setting with descriptions and guided input
- All values in human units (grams, percentages, on/off)
- Confirmation before every write, read-back verification after
- Factory defaults stored — restore anytime with option 4

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

- **Changes are RAM-only** — they revert on reboot or resume from sleep
- For persistence, set up a udev rule or systemd service (see below)
- The tool auto-detects the hidraw device (scans for vendor `2C2F`)
- No dependencies beyond Python 3 stdlib

## Making changes persistent

The simplest approach — a systemd service that runs after boot and after resume:

```bash
# /etc/systemd/system/sensel-touchpad.service
[Unit]
Description=Configure Sensel touchpad click force
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/sensel_set.py

[Install]
WantedBy=multi-user.target
```

*(A proper persistence script is a TODO — contributions welcome.)*

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

- ThinkPad X1 Carbon Gen 12 (21KC)
- Ubuntu 25.10 (kernel 6.17)
- Device: `SNSL0028:00 2C2F:0028`

Should work on other Sensel touchpads — the protocol is the same across models.

## License

MIT
