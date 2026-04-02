#!/usr/bin/env python3
"""
Sensel Touchpad Configuration Tool

Interactive tool to tune your ThinkPad's Sensel haptic touchpad on Linux.
Reads and writes firmware registers via the proprietary vendor HID pipe.

Protocol documented through interoperability analysis of the vendor HID interface.

Supported devices:
    - SNSL0028:00 2C2F:0028 (ThinkPad X1 Carbon Gen 12)
    - Should work with other Sensel touchpads (vendor 2C2F)

Usage:
    sudo python3 sensel_config.py
"""

import os, sys, time, select, re

# ─── Configuration ───────────────────────────────────────────────────────────

REPORT_ID = 0x09
PACKET_SIZE = 21

# ─── HID pipe transport ─────────────────────────────────────────────────────

def build_cmd(is_read, reg, size):
    """Build a 3-byte register read/write command."""
    byte0 = ((reg & 0x3F00) >> 7) | 1 | (0x80 if is_read else 0x00)
    return bytes([byte0, reg & 0xFF, size])


def pipe_write(fd, payload):
    """Send payload through the vendor HID pipe (report 0x09)."""
    buf = bytearray(PACKET_SIZE)
    buf[0] = REPORT_ID
    buf[1] = len(payload)
    buf[2:2 + len(payload)] = payload
    os.write(fd, bytes(buf))


def pipe_read(fd, timeout=1.0):
    """Read one packet from the HID pipe. Returns payload bytes or None."""
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    buf = os.read(fd, PACKET_SIZE)
    if len(buf) < 2 or buf[0] != REPORT_ID:
        return None
    return bytes(buf[2:2 + buf[1]])


def flush_pipe(fd):
    """Discard any pending data in the HID pipe."""
    while select.select([fd], [], [], 0.01)[0]:
        os.read(fd, PACKET_SIZE)


def collect_response(fd, min_bytes, timeout=1.0):
    """Read packets until we have at least min_bytes of data."""
    result = bytearray()
    deadline = time.time() + timeout
    while len(result) < min_bytes and time.time() < deadline:
        chunk = pipe_read(fd, timeout=max(0.05, deadline - time.time()))
        if chunk is None:
            break
        result.extend(chunk)
    return result


# ─── Register protocol ──────────────────────────────────────────────────────

def read_register(fd, reg, size=1):
    """
    Read a firmware register.

    Protocol:
        Send: [cmd_byte0, cmd_byte1, size]
        Recv: ACK(1) + reg_resp(1) + data_len(2 LE) + data(N) + checksum(1)

    Returns the data bytes.
    """
    flush_pipe(fd)
    pipe_write(fd, build_cmd(True, reg, size))
    resp = collect_response(fd, 4 + size + 1)

    if len(resp) < 4:
        raise RuntimeError(f"No response from register 0x{reg:04X}")
    if resp[0] != 1:  # READ_ACK
        raise RuntimeError(f"Read failed (ACK=0x{resp[0]:02X})")

    data_len = resp[2] | (resp[3] << 8)
    if len(resp) < 4 + data_len + 1:
        raise RuntimeError(f"Truncated response")

    data = resp[4:4 + data_len]
    checksum = resp[4 + data_len]
    if (sum(data) & 0xFF) != checksum:
        raise RuntimeError(f"Checksum error")

    return data


def write_register(fd, reg, value_bytes):
    """
    Write a firmware register.

    Protocol:
        Send: [cmd_byte0, cmd_byte1, size] + data + checksum
        Recv: WRITE_ACK(5) + reg_resp(1)

    Returns True on success.
    """
    flush_pipe(fd)
    cmd = build_cmd(False, reg, len(value_bytes))
    checksum = sum(value_bytes) & 0xFF
    pipe_write(fd, cmd + bytes(value_bytes) + bytes([checksum]))
    resp = collect_response(fd, 2)

    if len(resp) < 1 or resp[0] != 5:  # WRITE_ACK
        ack = resp[0] if resp else -1
        raise RuntimeError(f"Write failed (ACK=0x{ack:02X})")

    return True


# ─── Register definitions ───────────────────────────────────────────────────

class Reg:
    """A firmware register with human-friendly metadata."""

    def __init__(self, addr, name, desc, unit, default,
                 min_val, max_val, to_human, from_human, fmt_human):
        self.addr = addr
        self.name = name
        self.desc = desc
        self.unit = unit
        self.default = default
        self.min_val = min_val
        self.max_val = max_val
        self.to_human = to_human
        self.from_human = from_human
        self.fmt_human = fmt_human


def grams_reg(addr, name, desc, default):
    """Register whose raw value is grams/2."""
    return Reg(addr, name, desc, "grams",
               default, min_val=10, max_val=500,
               to_human=lambda v: v * 2,
               from_human=lambda g: max(1, min(255, round(g / 2))),
               fmt_human=lambda g: f"{g}g")


def percent_reg(addr, name, desc, default, max_val=100):
    """Register whose raw value is a percentage."""
    return Reg(addr, name, desc, "percent",
               default, min_val=0, max_val=max_val,
               to_human=lambda v: v,
               from_human=lambda p: max(0, min(max_val, round(p))),
               fmt_human=lambda p: f"{p}%")


def bool_reg(addr, name, desc, default):
    """Register that is on/off."""
    return Reg(addr, name, desc, "on/off",
               default, min_val=0, max_val=1,
               to_human=lambda v: v,
               from_human=lambda v: 1 if v else 0,
               fmt_human=lambda v: "ON" if v else "OFF")


# Factory defaults captured from a ThinkPad X1 Carbon Gen 12 on 2026-04-02.
SETTINGS = [
    grams_reg(0x0038, "Click force",
              "How hard you press the touchpad to trigger a click.\n"
              "    Lower = lighter click. The weight of a small coin is ~5g.\n"
              "    A typical mouse click is around 60-80g.",
              default=82),
    grams_reg(0x0090, "Click release threshold",
              "How much you must release pressure for the click to \"unclick\".\n"
              "    Should always be lower than click force (creates hysteresis).",
              default=54),

    grams_reg(0x0091, "Left zone click force",
              "Click force for the left button zone of the touchpad.",
              default=38),
    grams_reg(0x0092, "Left zone release",
              "Release threshold for the left zone.",
              default=25),
    grams_reg(0x0093, "Right zone click force",
              "Click force for the right button zone (right-click area).",
              default=38),
    grams_reg(0x0094, "Right zone release",
              "Release threshold for the right zone.",
              default=25),
    grams_reg(0x0095, "Middle zone click force",
              "Click force for the middle button zone.",
              default=38),
    grams_reg(0x0096, "Middle zone release",
              "Release threshold for the middle zone.",
              default=25),

    percent_reg(0x00AB, "Haptic feedback intensity",
                "How strong the vibration feedback feels when you click.\n"
                "    0% = no vibration, 100% = strongest buzz.",
                default=50),
    bool_reg(0x006E, "Haptic feedback enabled",
             "Master switch for haptic vibration feedback.",
             default=1),
]


# ─── Device detection ────────────────────────────────────────────────────────

def find_hidraw_device():
    """Auto-detect the Sensel touchpad hidraw device."""
    for name in sorted(os.listdir("/sys/class/hidraw/")):
        uevent_path = f"/sys/class/hidraw/{name}/device/uevent"
        try:
            with open(uevent_path) as f:
                content = f.read()
            if "00002C2F" in content:
                return f"/dev/{name}"
        except (FileNotFoundError, PermissionError):
            continue
    return None


# ─── UI helpers ──────────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"
UNDERLINE = "\033[4m"


def colored(text, *codes):
    if not sys.stdout.isatty():
        return str(text)
    return "".join(codes) + str(text) + RESET


def print_banner(device):
    print()
    print(colored("  Sensel Touchpad Configuration", BOLD, CYAN))
    print(colored(f"  Device: {device}", DIM))
    print(colored("  ─────────────────────────────", DIM))
    print()


def show_register_value(reg, raw_val):
    human = reg.to_human(raw_val)
    formatted = reg.fmt_human(human)
    marker = ""
    if raw_val != reg.default:
        marker = colored("  (modified)", YELLOW)
    default_formatted = reg.fmt_human(reg.to_human(reg.default))
    print(f"    Current : {colored(formatted, BOLD, GREEN)}{marker}")
    print(f"    Default : {default_formatted}")


def prompt_value(reg, current_raw):
    """Prompt the user for a new value. Returns raw byte, None (skip), or 'quit'."""
    current_human = reg.to_human(current_raw)

    if reg.unit == "on/off":
        current_str = "ON" if current_human else "OFF"
        print(f"\n    Currently: {colored(current_str, BOLD)}, type {colored('on', UNDERLINE)} or {colored('off', UNDERLINE)}")
        while True:
            ans = input("    > ").strip().lower()
            if ans in ('', 'skip', 's'):
                return None
            if ans in ('on', 'yes', '1', 'true', 'oui'):
                return 1
            if ans in ('off', 'no', '0', 'false', 'non'):
                return 0
            if ans in ('d', 'default'):
                return reg.default
            if ans in ('q', 'quit', 'exit'):
                return "quit"
            print("    Please type 'on' or 'off' (or Enter to skip)")
    else:
        unit_label = "g" if reg.unit == "grams" else ("%" if reg.unit == "percent" else "")
        print(f"\n    Enter new value in {colored(reg.unit, UNDERLINE)} ({reg.min_val}-{reg.max_val}{unit_label})")
        print(f"    Or: {colored('d', UNDERLINE)}=restore default, Enter=skip, {colored('q', UNDERLINE)}=quit")

        while True:
            ans = input(f"    [{reg.fmt_human(current_human)}] > ").strip().lower()
            if ans in ('', 'skip', 's'):
                return None
            if ans in ('d', 'default'):
                return reg.default
            if ans in ('q', 'quit', 'exit'):
                return "quit"
            ans = ans.rstrip('g').rstrip('%').strip()
            try:
                human_val = float(ans)
            except ValueError:
                print("    Not a number. Try again.")
                continue
            if human_val < reg.min_val or human_val > reg.max_val:
                print(f"    Out of range ({reg.min_val}-{reg.max_val}). Try again.")
                continue
            return reg.from_human(human_val)


# ─── Main flows ──────────────────────────────────────────────────────────────

def read_all_values(fd):
    """Read and display all register values."""
    print(colored("  Current settings:", BOLD))
    print()
    for reg in SETTINGS:
        try:
            raw = read_register(fd, reg.addr)[0]
            human = reg.to_human(raw)
            formatted = reg.fmt_human(human)
            default_formatted = reg.fmt_human(reg.to_human(reg.default))
            mod = colored(" *", YELLOW) if raw != reg.default else ""
            print(f"    {reg.name:<30} {colored(formatted, BOLD):>15}   "
                  f"{colored(f'(default: {default_formatted})', DIM)}{mod}")
        except Exception as e:
            print(f"    {reg.name:<30} {colored('ERROR', RED):>15}   {e}")
    print()


def interactive_tune(fd):
    """Walk through each setting interactively."""
    print(colored("  Interactive tuning mode", BOLD))
    print(colored("  Walk through each setting. Press Enter to skip, 'q' to quit.", DIM))
    print()

    changes = []
    for i, reg in enumerate(SETTINGS):
        try:
            current_raw = read_register(fd, reg.addr)[0]
        except Exception as e:
            print(f"  {colored('!', RED)} Cannot read {reg.name}: {e}")
            continue

        print(colored(f"  [{i+1}/{len(SETTINGS)}] {reg.name}", BOLD, CYAN))
        for line in reg.desc.split('\n'):
            print(f"  {colored(line.strip(), DIM)}")
        show_register_value(reg, current_raw)

        new_raw = prompt_value(reg, current_raw)
        if new_raw == "quit":
            print(f"\n  Quit. {len(changes)} change(s) applied so far.")
            return changes
        if new_raw is None or new_raw == current_raw:
            print(colored("    Skipped.", DIM))
        else:
            try:
                write_register(fd, reg.addr, bytes([new_raw]))
                time.sleep(0.05)
                verify = read_register(fd, reg.addr)[0]
                old_h = reg.fmt_human(reg.to_human(current_raw))
                new_h = reg.fmt_human(reg.to_human(new_raw))
                if verify == new_raw:
                    print(colored(f"    Done: {old_h} -> {new_h}", GREEN))
                    changes.append((reg, current_raw, new_raw))
                else:
                    print(colored(f"    WARNING: wrote {new_raw} but read back {verify}", RED))
            except Exception as e:
                print(colored(f"    Write failed: {e}", RED))
        print()

    return changes


def quick_click_adjust(fd):
    """Quickly adjust the main click force with guided ranges."""
    click_reg = SETTINGS[0]
    release_reg = SETTINGS[1]

    try:
        click_raw = read_register(fd, click_reg.addr)[0]
        release_raw = read_register(fd, release_reg.addr)[0]
    except Exception as e:
        print(colored(f"  Cannot read: {e}", RED))
        return

    print(colored("  Quick click force adjustment", BOLD, CYAN))
    print(colored("  How hard you must press to click the touchpad.", DIM))
    print()
    print(f"    Light click   :  60-80g   (like tapping a table)")
    print(f"    Medium click  : 100-130g   (normal laptop touchpad)")
    print(f"    Firm click    : 150-200g   (deliberate press)")
    print()
    show_register_value(click_reg, click_raw)
    print()

    new_raw = prompt_value(click_reg, click_raw)
    if new_raw == "quit" or new_raw is None or new_raw == click_raw:
        if new_raw == click_raw:
            print(colored("    No change.", DIM))
        return

    new_release = max(1, round(new_raw * 0.65))
    new_click_g = click_reg.to_human(new_raw)
    new_release_g = release_reg.to_human(new_release)

    print()
    print(f"    Click force  : {click_reg.fmt_human(click_reg.to_human(click_raw))} -> "
          f"{colored(click_reg.fmt_human(new_click_g), BOLD, GREEN)}")
    print(f"    Release      : {release_reg.fmt_human(release_reg.to_human(release_raw))} -> "
          f"{colored(release_reg.fmt_human(new_release_g), GREEN)} (auto: 65% of click)")
    print()
    confirm = input("    Apply? [y/N] ").strip().lower()
    if confirm != 'y':
        print("    Aborted.")
        return

    try:
        write_register(fd, click_reg.addr, bytes([new_raw]))
        time.sleep(0.05)
        write_register(fd, release_reg.addr, bytes([new_release]))
        time.sleep(0.05)
        v1 = read_register(fd, click_reg.addr)[0]
        v2 = read_register(fd, release_reg.addr)[0]
        if v1 == new_raw and v2 == new_release:
            print(colored("    Applied! Try clicking your touchpad now.", GREEN, BOLD))
        else:
            print(colored(f"    WARNING: readback mismatch (click={v1}, release={v2})", RED))
    except Exception as e:
        print(colored(f"    Error: {e}", RED))

    print(colored("    Changes are RAM-only — revert on reboot/sleep.", DIM))


def restore_defaults(fd):
    """Restore all registers to factory defaults."""
    print(colored("  Restoring factory defaults...", BOLD))
    print()
    for reg in SETTINGS:
        try:
            current = read_register(fd, reg.addr)[0]
            if current == reg.default:
                print(f"    {reg.name:<30} already at default "
                      f"({reg.fmt_human(reg.to_human(reg.default))})")
                continue
            write_register(fd, reg.addr, bytes([reg.default]))
            time.sleep(0.05)
            verify = read_register(fd, reg.addr)[0]
            old_h = reg.fmt_human(reg.to_human(current))
            new_h = reg.fmt_human(reg.to_human(reg.default))
            if verify == reg.default:
                print(f"    {reg.name:<30} {old_h} -> {colored(new_h, GREEN)}")
            else:
                print(colored(f"    {reg.name:<30} FAILED (read back {verify})", RED))
        except Exception as e:
            print(colored(f"    {reg.name:<30} ERROR: {e}", RED))
    print()
    print(colored("  Done. All settings restored to factory defaults.", GREEN))


def main_menu(fd):
    """Main interactive menu loop."""
    while True:
        print()
        print(colored("  What would you like to do?", BOLD))
        print()
        print(f"    {colored('1', BOLD, CYAN)}  Show current settings")
        print(f"    {colored('2', BOLD, CYAN)}  Tune settings interactively")
        print(f"    {colored('3', BOLD, CYAN)}  Quick adjust: click force only")
        print(f"    {colored('4', BOLD, CYAN)}  Restore factory defaults")
        print(f"    {colored('q', BOLD, CYAN)}  Quit")
        print()

        choice = input("  > ").strip().lower()

        if choice in ('1', 'show', 'read'):
            print()
            read_all_values(fd)

        elif choice in ('2', 'tune', 'interactive'):
            print()
            changes = interactive_tune(fd)
            if changes:
                print(colored(f"  Summary: {len(changes)} setting(s) changed.", BOLD, GREEN))
                for reg, old, new in changes:
                    old_h = reg.fmt_human(reg.to_human(old))
                    new_h = reg.fmt_human(reg.to_human(new))
                    print(f"    {reg.name}: {old_h} -> {colored(new_h, GREEN)}")
                print()
                print(colored("  Note: changes are RAM-only. They revert on reboot/sleep.", DIM))

        elif choice in ('3', 'quick', 'click'):
            print()
            quick_click_adjust(fd)

        elif choice in ('4', 'defaults', 'reset', 'restore'):
            print()
            confirm = input(colored("  Restore ALL settings to factory defaults? [y/N] ",
                                    BOLD)).strip().lower()
            if confirm == 'y':
                restore_defaults(fd)
            else:
                print("  Aborted.")

        elif choice in ('q', 'quit', 'exit', ''):
            print(colored("  Bye!", DIM))
            break

        else:
            print(colored("  Unknown option. Try 1, 2, 3, 4, or q.", DIM))


# ─── CLI flag helpers ────────────────────────────────────────────────────────

def name_to_flag(name):
    """Convert register name to CLI flag: 'Click force' -> '--set-click-force'."""
    return "--set-" + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def flag_to_reg(flag):
    """Find a register matching a --set-xxx flag. Returns (Reg, value_str) or None."""
    for reg in SETTINGS:
        if flag == name_to_flag(reg.name):
            return reg
    return None


def print_cli_help():
    """Print non-interactive usage."""
    print(f"\nUsage: sudo python3 {sys.argv[0]} [OPTIONS]")
    print(f"\nWith no options, starts interactive mode.\n")
    print("Options:")
    print(f"  {'--show':<45} Show current settings and exit")
    print(f"  {'--defaults':<45} Restore factory defaults and exit")
    print()
    print("Set individual values (in human units — grams, %, on/off):")
    for reg in SETTINGS:
        flag = name_to_flag(reg.name)
        if reg.unit == "on/off":
            example = f"{flag}=on|off"
        elif reg.unit == "grams":
            example = f"{flag}=<{reg.min_val}-{reg.max_val}g>"
        else:
            example = f"{flag}=<{reg.min_val}-{reg.max_val}%>"
        default_h = reg.fmt_human(reg.to_human(reg.default))
        print(f"  {example:<45} {reg.name} (default: {default_h})")
    print()
    print("Example:")
    print(f"  sudo python3 {sys.argv[0]} \\")
    print(f"    --set-click-force=76 \\")
    print(f"    --set-click-release-threshold=50 \\")
    print(f"    --set-haptic-feedback-intensity=35")
    print()


def parse_flag_value(reg, value_str):
    """Parse a human-unit value string for a register. Returns raw byte value."""
    if reg.unit == "on/off":
        if value_str.lower() in ('on', 'yes', '1', 'true'):
            return 1
        if value_str.lower() in ('off', 'no', '0', 'false'):
            return 0
        raise ValueError(f"Expected on/off, got '{value_str}'")
    try:
        human_val = float(value_str.rstrip('g').rstrip('%'))
    except ValueError:
        raise ValueError(f"Not a number: '{value_str}'")
    if human_val < reg.min_val or human_val > reg.max_val:
        raise ValueError(f"Out of range ({reg.min_val}-{reg.max_val}), got {human_val}")
    return reg.from_human(human_val)


def run_cli_set(fd, set_args):
    """Apply --set-xxx=value arguments. Returns True if all succeeded."""
    ok = True
    for flag, value_str in set_args:
        reg = flag_to_reg(flag)
        if reg is None:
            print(f"  Unknown flag: {flag}")
            ok = False
            continue
        try:
            raw = parse_flag_value(reg, value_str)
            current = read_register(fd, reg.addr)[0]
            if current == raw:
                print(f"  {reg.name}: already at {reg.fmt_human(reg.to_human(raw))}")
                continue
            write_register(fd, reg.addr, bytes([raw]))
            time.sleep(0.05)
            verify = read_register(fd, reg.addr)[0]
            old_h = reg.fmt_human(reg.to_human(current))
            new_h = reg.fmt_human(reg.to_human(raw))
            if verify == raw:
                print(f"  {reg.name}: {old_h} -> {new_h}")
            else:
                print(f"  {reg.name}: WRITE FAILED (read back {verify})")
                ok = False
        except Exception as e:
            print(f"  {reg.name}: {e}")
            ok = False
    return ok


# ─── Entry point ─────────────────────────────────────────────────────────────

def open_device():
    """Find, open and sanity-check the Sensel hidraw device."""
    if os.geteuid() != 0:
        print(f"\n  This tool needs root access to talk to the touchpad.")
        print(f"  Run: sudo python3 {sys.argv[0]}\n")
        sys.exit(1)

    device = find_hidraw_device()
    if device is None:
        print("\n  No Sensel touchpad found (vendor 2C2F).")
        print("  Check: cat /sys/class/hidraw/hidraw*/device/uevent | grep 2C2F\n")
        sys.exit(1)

    try:
        fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        print(f"\n  Cannot open {device} — permission denied.")
        print(f"  Run: sudo python3 {sys.argv[0]}\n")
        sys.exit(1)

    try:
        read_register(fd, 0x006E)
    except Exception as e:
        print(f"\n  Cannot communicate with touchpad on {device}: {e}\n")
        os.close(fd)
        sys.exit(1)

    return fd, device


def main():
    args = sys.argv[1:]

    # Help
    if any(a in ('-h', '--help', 'help') for a in args):
        print_cli_help()
        sys.exit(0)

    # Parse --set-xxx=value and --show/--defaults flags
    set_args = []
    show_only = False
    restore = False
    for arg in args:
        if arg == '--show':
            show_only = True
        elif arg == '--defaults':
            restore = True
        elif arg.startswith('--set-') and '=' in arg:
            flag, value = arg.split('=', 1)
            set_args.append((flag, value))
        else:
            print(f"  Unknown argument: {arg}")
            print(f"  Run with --help for usage.\n")
            sys.exit(1)

    # Non-interactive: --show
    if show_only:
        fd, device = open_device()
        print_banner(device)
        read_all_values(fd)
        os.close(fd)
        return

    # Non-interactive: --defaults
    if restore:
        fd, device = open_device()
        restore_defaults(fd)
        os.close(fd)
        return

    # Non-interactive: --set-xxx=value
    if set_args:
        # Validate all flags before opening device
        for flag, value_str in set_args:
            if flag_to_reg(flag) is None:
                print(f"  Unknown flag: {flag}")
                print(f"  Run with --help for available flags.\n")
                sys.exit(1)
        fd, device = open_device()
        ok = run_cli_set(fd, set_args)
        os.close(fd)
        sys.exit(0 if ok else 1)

    # Interactive mode (no args)
    fd, device = open_device()
    print_banner(device)
    read_all_values(fd)
    main_menu(fd)
    os.close(fd)


if __name__ == "__main__":
    main()
