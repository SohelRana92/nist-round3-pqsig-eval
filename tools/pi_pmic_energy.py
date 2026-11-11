#!/usr/bin/env python3
"""pi_pmic_energy.py - energy per operation on the Raspberry Pi 5 from its
own power-management chip (PMIC), without external hardware.

  python3 tools/pi_pmic_energy.py            # the Pi energy set (paper/data/energy_plan.json)
  python3 tools/pi_pmic_energy.py --only mldsa-44-ref

The Pi 5 PMIC (Renesas DA9091) reports the current and voltage of each of
its rails; `vcgencmd pmic_read_adc` reads them. A sampler on core 0 polls it
in a loop and records P = sum over rails of I x V, with CLOCK_MONOTONIC
time stamps. The benchmark runs on core 3 and writes its window edges to a
marker file (HARNESS_MARKER_FILE) in the same clock. The two are merged into
a log in the format of energy/energy_analyze.py, which gives

    E_op = (P_window - P_idle) * T / N

with P_idle from the middle half of the rest after each window (the rest is
a sleep: 1 s to settle, then 2 s). This covers the PMIC rails (SoC core,
memory, I/O, wireless, HDMI) but not the 5 V input and the PMIC's own
conversion loss.

Every recipe writes results/raw/energy/pi5_pmic/<recipe>_{log,bench}.csv and
appends to results/energy_summary.csv (platform pi5) and
results/energy_board.csv. Finished recipes have a .done file and are skipped,
so the script can be started again after a power cut.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
RAIL = re.compile(r"^\s*(\S+)_([AV])\s+\w+\(\d+\)=([0-9.]+)[AV]")


def pmic_power():
    out = subprocess.run(["vcgencmd", "pmic_read_adc"], capture_output=True, text=True).stdout
    a, v = {}, {}
    for line in out.splitlines():
        m = RAIL.match(line)
        if m:
            (a if m.group(2) == "A" else v)[m.group(1)] = float(m.group(3))
    return sum(a[k] * v[k] for k in a if k in v), len([k for k in a if k in v])


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        os.sched_setaffinity(0, {0})
        while not self.stop:
            t0 = time.monotonic_ns()
            p, _ = pmic_power()
            t1 = time.monotonic_ns()
            self.rows.append(((t0 + t1) // 2, p))


def merge(samples, edges, path):
    """Writes the energy_analyze.py log: marker = level of the last edge
    before each sample."""
    edges = sorted(edges)
    k, level = 0, 0
    with open(path, "w") as f:
        f.write("t_ns,sensor,channel,bus_V,shunt_V,current_A,power_W,marker\n")
        for t, p in samples:
            while k < len(edges) and edges[k][0] <= t:
                level = edges[k][1]
                k += 1
            f.write("%d,pmic,0,0,0,0,%.6f,%d\n" % (t, p, level))


def ensure_built(n):
    bench = os.path.join(TOP, "build", "pi5", n, "bench")
    srcs = [os.path.join(TOP, "harness", "src", "bench_main.c"),
            os.path.join(TOP, "harness", "platform", "plat_linux.c")]
    if not os.path.exists(bench) or os.path.getmtime(bench) < max(os.path.getmtime(x) for x in srcs):
        subprocess.run([sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n, "--platform", "pi5"],
                       capture_output=True)
    return bench if os.path.exists(bench) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--core", default="3")
    ap.add_argument("--seconds", type=float, default=15, help="window length (the plan has 10 s)")
    ap.add_argument("--windows", type=int, default=10, help="windows per operation (the plan has 5)")
    a = ap.parse_args()
    for g in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"):
        subprocess.run("echo performance | sudo -n tee %s > /dev/null" % g, shell=True)
    p, rails = pmic_power()
    t0 = time.monotonic()
    for _ in range(20):
        pmic_power()
    rate = 20 / (time.monotonic() - t0)
    print("PMIC: %d rails, %.3f W now, %.0f samples/s" % (rails, p, rate), flush=True)
    if rails < 5:
        sys.exit("vcgencmd pmic_read_adc gave too few rails")
    plan = json.load(open(os.path.join(TOP, "paper", "data", "energy_plan.json")))["pi5"]
    d = os.path.join(TOP, "results", "raw", "energy", "pi5_pmic")
    os.makedirs(d, exist_ok=True)
    for e in plan:
        n = e["recipe"]
        if a.only and n not in a.only:
            continue
        done = os.path.join(d, n + ".done")
        if os.path.exists(done) and not a.force:
            print("skip %s (done)" % n, flush=True)
            continue
        bench = ensure_built(n)
        if not bench:
            print("%s: build failed" % n, flush=True)
            continue
        thr = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout.strip()
        print("== %s  %s" % (n, thr), flush=True)
        mark = os.path.join(d, n + "_marker.txt")
        logp = os.path.join(d, n + "_log.csv")
        benchp = os.path.join(d, n + "_bench.csv")
        if os.path.exists(mark):
            os.remove(mark)
        s = Sampler()
        s.start()
        time.sleep(3)
        with open(benchp, "w") as f:
            f.write("NOTE,pmic_energy,%s,%s,pmic_samples_per_s,%.0f\n" % (n, thr, rate))
            for o in e["ops"]:
                win = a.windows if o["windows"] >= 5 else o["windows"]     # slow operations keep 3
                r = subprocess.run(["taskset", "-c", a.core, bench, "energy", o["op"], str(max(a.seconds, o["seconds"])),
                                    str(win)], env=dict(os.environ, HARNESS_MARKER_FILE=mark),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                f.write(r.stdout)
                if r.returncode:
                    f.write("ERROR,exit_code,%d,%s\n" % (r.returncode, o["op"]))
        time.sleep(3)
        s.stop = True
        s.join()
        edges = [tuple(int(x) for x in l.split(",")) for l in open(mark) if l.strip()] if os.path.exists(mark) else []
        merge(s.rows, edges, logp)
        r = subprocess.run([sys.executable, os.path.join(TOP, "energy", "energy_analyze.py"), "--log", logp,
                            "--bench", benchp, "--label", "pi5"], cwd=TOP, capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        for line in out.splitlines():
            if "E_op mean" in line or "WARNING" in line or "Error" in line or "error" in line:
                print("   " + line.strip(), flush=True)
        if r.returncode == 0 and "WARNING" not in out:
            open(done, "w").close()
        else:
            print("   %s: check %s; run again with --only %s --force" % (n, logp, n), flush=True)
    print("all done", flush=True)


if __name__ == "__main__":
    main()
