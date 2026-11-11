#!/usr/bin/env python3
"""esp32_capture.py - read harness lines from an ESP32 (or MicroBlaze UART)
until DONE and save them as CSV.

Usage:
  tools/esp32_capture.py --port /dev/ttyUSB0 --out results/esp32_mayo1.csv
  tools/esp32_capture.py --port /dev/ttyUSB1 --out results/mb_mayo1.csv

Needs pyserial (the ESP-IDF Python environment already has it). The
script resets the board through the RTS line (the EN pin on DevKit boards)
after opening the port, so the run starts from boot and no button press
is needed; use --no-reset to press EN by hand instead.
Every serial line also goes to OUT.log. A panic, a stack overflow or a
watchdog reboot ends the capture with an ERROR,crash row (exit code 3),
because that is a feasibility result, not something to wait out.
"""
import argparse
import sys
import time

import serial

KEEP = ("SIZES", "KAT", "SPEED", "STACK", "ENERGY", "NOTE", "ERROR")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout-h", type=float, default=24.0)
    ap.add_argument("--no-reset", action="store_true")
    a = ap.parse_args()
    # Windows consoles use cp1252; boot-ROM noise at the wrong baud rate
    # decodes to characters it cannot print, so replace them instead of failing.
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    s = serial.Serial(a.port, a.baud, timeout=1)
    if not a.no_reset:
        s.dtr = False          # IO0 high: normal boot, not download mode
        s.rts = True           # EN low: hold in reset
        time.sleep(0.15)
        s.rts = False          # release EN
    crash = ("Guru Meditation", "stack overflow", "abort() was called", "Task watchdog got triggered")
    boots = 0
    end = time.time() + a.timeout_h * 3600
    n = 0
    with open(a.out, "w", encoding="ascii", errors="replace", newline="\n") as f, \
            open(a.out + ".log", "w", encoding="utf-8", errors="replace", newline="\n") as lg:
        while time.time() < end:
            raw = s.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").strip()
            lg.write(line + "\n")
            lg.flush()
            # A boot banner after the harness has started printing is a reboot.
            if line.startswith("rst:") and n > 0:
                boots += 1
            if any(c in line for c in crash) or boots > 0:
                f.write("ERROR,crash,%s\n" % line.replace(",", ";"))
                print("board crashed or rebooted:", line)
                # Keep the panic dump (PC, EXCVADDR, backtrace) in the log:
                # it shows whether a crash is a NULL store after a failed
                # allocation or a stack overrun.
                stop = time.time() + 3
                while time.time() < stop:
                    more = s.readline()
                    if more:
                        lg.write(more.decode("utf-8", "replace").rstrip() + "\n")
                lg.flush()
                print("see", a.out + ".log")
                sys.exit(3)
            if line == "DONE":
                print("DONE after", n, "lines")
                return
            tag = line.split(",", 1)[0]
            if tag.endswith("_HDR") or tag in KEEP:
                f.write(line + "\n")
                f.flush()
                n += 1
                if tag in ("NOTE", "ERROR", "SIZES", "KAT"):
                    print(line)
    sys.exit("timeout before DONE")


if __name__ == "__main__":
    main()
