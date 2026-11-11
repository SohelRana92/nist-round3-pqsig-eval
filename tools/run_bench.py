#!/usr/bin/env python3
"""run_bench.py - run the speed, stack and size measurements for many
recipes on a Linux board (Raspberry Pi 5 or the Ryzen 9 9950X).

  tools/run_bench.py --platform x86 --category 1
  tools/run_bench.py --platform pi5 --match mayo --runs 1000 --warmup 10
  tools/run_bench.py --platform x86 --match=-opt- --core 2

For every recipe it (re)builds with tools/hbuild.py unless --no-build,
then runs, pinned to one core with taskset:
  bench sizes
  bench stack
  bench speed RUNS WARMUP
and writes the raw lines to results/raw/<platform>/<recipe>.csv.
Nothing is averaged here; tools/summarize.py does that.

The recipe must have passed tools/kat_all.py on the same platform first.
run_bench.py refuses a recipe whose KAT row in results/kat_<platform>.csv
is missing or not PASS/EXTERNAL, unless --skip-kat-check is given.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from kat_all import category  # noqa: E402


def kat_ok(platform):
    ok = set()
    for f in os.listdir(os.path.join(TOP, "results")):
        # kat_pi5.csv and kat_pi5_cat1.csv count; kat_pi5-qemu.csv does not.
        if f == "kat_%s.csv" % platform or (f.startswith("kat_%s_" % platform) and f.endswith(".csv")):
            for row in csv.DictReader(open(os.path.join(TOP, "results", f))):
                if row["status"] in ("PASS", "EXTERNAL"):
                    ok.add(row["recipe"])
    return ok


def throttled():
    """Raspberry Pi 5: vcgencmd get_throttled must read 0x0 before and after
    a run. Other boards print not_available."""
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True)
        return r.stdout.strip().split("=")[-1] or "not_available"
    except FileNotFoundError:
        return "not_available"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=["pi5", "x86", "x86-generic"])
    ap.add_argument("--category")
    ap.add_argument("--match", default="")
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--core", type=int, default=2, help="CPU core for taskset")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--force", action="store_true", help="measure again even if a finished CSV exists")
    ap.add_argument("--skip-kat-check", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    a = ap.parse_args()

    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    names = [n for n in sorted(recipes) if a.match in n
             and a.platform in recipes[n].get("platforms", [a.platform])]
    if a.category:
        names = [n for n in names if category(recipes[n]) == a.category]
    # After a power cut the Pi boots with the default governor (1.5 to
    # 2.4 GHz). Mixed clocks would spoil the timings, so stop here.
    gov = "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_governor" % a.core
    if a.platform == "pi5" and os.path.exists(gov) and open(gov).read().strip() != "performance":
        sys.exit("governor of core %d is not 'performance'. Run first:\n"
                 "  echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" % a.core)
    okset = kat_ok(a.platform)
    raw = os.path.join(TOP, "results", "raw", a.platform)
    os.makedirs(raw, exist_ok=True)
    for n in names:
        if not a.skip_kat_check and n not in okset:
            print("skip %-40s no passing KAT row on %s" % (n, a.platform))
            continue
        out = os.path.join(raw, n + ".csv")
        # Resume after a power cut: a finished recipe ends with its
        # THROTTLE,after row and is skipped (before any rebuild) unless
        # --force. Output goes to a .part file first, so a cut never leaves
        # a half file that looks finished.
        if not a.force and os.path.exists(out) and "THROTTLE,after," in open(out).read():
            print("skip %-40s already measured (use --force to redo)" % n)
            continue
        b = os.path.join(TOP, "build", a.platform, n)
        if not a.no_build or not os.path.exists(os.path.join(b, "bench")):
            cmd = [sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n, "--platform", a.platform]
            for s in a.set:
                cmd += ["--set", s]
            if subprocess.run(cmd, capture_output=True).returncode != 0:
                print("BUILD_FAIL", n)
                continue
        t0 = time.time()
        part = out + ".part"
        with open(part, "w") as f:
            f.write("THROTTLE,before,%s\n" % throttled())
            for mode in (["sizes"], ["stack"], ["speed", str(a.runs), str(a.warmup)]):
                r = subprocess.run(["taskset", "-c", str(a.core), os.path.join(b, "bench")] + mode,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                f.write(r.stdout)
                if r.returncode != 0:
                    f.write("ERROR,exit_code,%d,%s\n" % (r.returncode, " ".join(mode)))
            after = throttled()
            f.write("THROTTLE,after,%s\n" % after)
        os.replace(part, out)
        if after not in ("0x0", "not_available"):
            print("WARNING %s: vcgencmd get_throttled=%s; discard and rerun this recipe" % (n, after))
        print("done %-40s %6.1f s  -> %s" % (n, time.time() - t0, os.path.relpath(out, TOP)), flush=True)


if __name__ == "__main__":
    main()
