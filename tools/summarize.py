#!/usr/bin/env python3
"""summarize.py - turn raw harness output into the tables of the paper.

  tools/summarize.py                     all platforms found under results/raw
  tools/summarize.py --platform esp32

Inputs
  results/raw/<platform>/<recipe>.csv   from run_bench.py (Linux boards) or
                                        tools/esp32_capture.py / the MicroBlaze
                                        UART log saved under the same name
Outputs (one row per scheme, parameter set, variant and platform)
  results/summary_speed.csv   op, n, median cycles, Q1, Q3, IQR, p99, median ns,
                              min, max, all_ok
  results/summary_stack.csv   op, peak stack bytes
  results/summary_sizes.csv   pk, sk, sig bytes
  results/summary_code.csv    text, data, bss of libscheme objects
                              (build/<platform>/<recipe>/size.txt, Linux only)

Medians and quartiles use the "linear" (type 7) definition, the default
of numpy.percentile, written out here so no extra package is needed.
A run with ok=0 (verification failed) makes all_ok=0 for that row, and the
paper must not report such a row.
"""
import argparse
import csv
import glob
import os
import re

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pct(sorted_v, q):
    if not sorted_v:
        return float("nan")
    pos = (len(sorted_v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (pos - lo)


def code_size(platform, recipe):
    f = os.path.join(TOP, "build", platform, recipe, "size.txt")
    if not os.path.exists(f):
        return None
    for line in open(f):
        if "(TOTALS)" in line:
            p = line.split()
            return int(p[0]), int(p[1]), int(p[2])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform")
    a = ap.parse_args()
    plats = [a.platform] if a.platform else sorted(os.listdir(os.path.join(TOP, "results", "raw")))
    speed, stack, sizes, code = [], [], [], []
    for p in plats:
        for f in sorted(glob.glob(os.path.join(TOP, "results", "raw", p, "*.csv"))):
            recipe = os.path.basename(f)[:-4]
            runs = {}
            noop = None
            first_stack = len(stack)
            for row in csv.reader(open(f)):
                if not row:
                    continue
                if row[0] == "SPEED":
                    key = tuple(row[1:5]) + (row[5], row[6])
                    runs.setdefault(key, []).append((int(row[8]), int(row[9]), int(row[12])))
                elif row[0] == "STACK":
                    stack.append(row[1:5] + [row[5], row[6], row[7]])
                    if row[5] == "noop":
                        noop = int(row[6])
                elif row[0] == "SIZES":
                    sizes.append(row[1:])
            # net stack = peak minus the harness's own no-op baseline
            for st in stack[first_stack:]:
                st.append(int(st[5]) - noop if noop is not None else "")
            for key, v in runs.items():
                cyc = sorted(x[0] for x in v)
                ns = sorted(x[1] for x in v)
                q1, med, q3 = pct(cyc, 0.25), pct(cyc, 0.5), pct(cyc, 0.75)
                speed.append(list(key[:4]) + [key[4], key[5], len(v), "%.0f" % med, "%.0f" % q1, "%.0f" % q3,
                                              "%.0f" % (q3 - q1), "%.0f" % pct(cyc, 0.99), "%.0f" % pct(ns, 0.5), cyc[0], cyc[-1],
                                              int(all(x[2] == 1 for x in v))])
            cs = code_size(p, recipe)
            if cs:
                code.append([recipe, p, cs[0], cs[1], cs[2]])
    out = os.path.join(TOP, "results")
    with open(os.path.join(out, "summary_speed.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "variant", "platform", "timer", "op", "n", "median_cycles", "q1", "q3",
                    "iqr", "p99_cycles", "median_ns", "min_cycles", "max_cycles", "all_ok"])
        w.writerows(speed)
    with open(os.path.join(out, "summary_stack.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "variant", "platform", "op", "peak_stack_bytes", "ok", "net_stack_bytes"])
        w.writerows(stack)
    with open(os.path.join(out, "summary_sizes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "variant", "platform", "pk_bytes", "sk_bytes", "sig_bytes"])
        w.writerows(sizes)
    with open(os.path.join(out, "summary_code.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipe", "platform", "text", "data", "bss"])
        w.writerows(code)
    print("speed rows %d, stack rows %d, size rows %d, code rows %d" % (len(speed), len(stack), len(sizes), len(code)))


if __name__ == "__main__":
    main()
