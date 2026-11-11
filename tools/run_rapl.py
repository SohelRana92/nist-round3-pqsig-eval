#!/usr/bin/env python3
"""run_rapl.py - RAPL energy per operation on the Ryzen 9 9950X (the memory and energy table,
Fig. 4) for the timed x86 variant of every scheme.

  python3 tools/run_rapl.py              # all schemes, keypair/sign/verify
  python3 tools/run_rapl.py --list

For each recipe and operation: bench energy OP SECONDS WINDOWS on one core
with HARNESS_RAPL set, written to results/raw/x86/rapl_<recipe>_<op>.csv,
then energy/rapl_analyze.py appends the result to results/energy_summary.csv.
A finished file (it holds its last ENERGY window) is skipped, so the script
can be started again after a cut.

The package energy counter is readable by root only; run once per boot:
  sudo chmod o+r /sys/class/powercap/intel-rapl:0/energy_uj
The package domain is found by its name.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)


def package_domain():
    for d in sorted(glob.glob("/sys/class/powercap/intel-rapl:*")):
        try:
            if open(os.path.join(d, "name")).read().strip().startswith("package"):
                return os.path.join(d, "energy_uj")
        except OSError:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--windows", type=int, default=5)
    ap.add_argument("--core", default="2")
    ap.add_argument("--ops", default="keypair,sign,verify")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    sets = json.load(open(os.path.join(TOP, "paper", "data", "representative_sets.json")))["sets"]
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    names = []
    for scheme, s in sets.items():
        var = s["variant"].get("x86", s["variant"]["default"])
        for k, v in sorted(recipes.items()):
            if v["scheme"].replace("-", "").lower() == scheme.replace("-", "").lower() and \
                    v["param"] == s["param"] and v["variant"] == var:
                names.append(k)
                break
    for n in names:
        print("plan", n)
    if a.list:
        return
    dom = package_domain()
    if not dom or not os.access(dom, os.R_OK):
        sys.exit("RAPL package counter not readable: sudo chmod o+r %s" % (dom or "/sys/class/powercap/intel-rapl:0/energy_uj"))
    raw = os.path.join(TOP, "results", "raw", "x86")
    os.makedirs(raw, exist_ok=True)
    for n in names:
        bench = os.path.join(TOP, "build", "x86", n, "bench")
        srcs = [os.path.join(TOP, "harness", "src", "bench_main.c"),
                os.path.join(TOP, "harness", "platform", "plat_linux.c")]
        if not os.path.exists(bench) or os.path.getmtime(bench) < max(os.path.getmtime(x) for x in srcs):
            subprocess.run([sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n, "--platform", "x86"],
                           capture_output=True)
        for op in a.ops.split(","):
            out = os.path.join(raw, "rapl_%s_%s.csv" % (n, op))
            last = ",%s,%d," % (op, a.windows - 1)
            if os.path.exists(out) and any(l.startswith("ENERGY") and last in l for l in open(out)):
                print("skip %-36s %-8s done" % (n, op))
                continue
            with open(out + ".part", "w") as f:
                r = subprocess.run(["taskset", "-c", a.core, bench, "energy", op, str(a.seconds), str(a.windows)],
                                   stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, HARNESS_RAPL=dom))
            os.replace(out + ".part", out)
            an = subprocess.run([sys.executable, os.path.join(TOP, "energy", "rapl_analyze.py"), out],
                                capture_output=True, text=True, cwd=TOP)
            print("done %-36s %-8s rc=%d  %s" % (n, op, r.returncode, (an.stdout + an.stderr).strip()[-160:]),
                  flush=True)


if __name__ == "__main__":
    main()
