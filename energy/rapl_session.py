#!/usr/bin/env python3
"""rapl_session.py - RAPL energy per operation against one idle level for
the whole session.

  python3 energy/rapl_session.py results/raw/x86/rapl_*.csv

rapl_analyze.py takes P_idle from the rest after each window. For most
recipes the package is back at idle (about 14 W) after the 1 s settling
time. After FAEST and MQOM windows it is not: their rests stay at 17-25 W,
so a per-rest P_idle hides part of the energy and E_op scatters by up to
+-40 %. This script uses P_idle_session = median power of every rest in
the given files (all recipes of one run), so

    E_op = (P_window - P_idle_session) * T / N

and writes results/energy_summary_x86_session.csv with the per-rest value
next to it for comparison.
"""
import csv
import math
import os
import statistics as st
import sys

T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def read(path):
    rapl, ener = [], []
    for row in csv.reader(open(path)):
        if row and row[0] == "RAPL":
            rapl.append((row[1], int(row[2]), int(row[3])))
        elif row and row[0] == "ENERGY":
            ener.append(row)
    return rapl, ener


def ci(v):
    return T95.get(len(v) - 1, 1.96) * st.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else float("nan")


def main(files):
    data = {f: read(f) for f in files}
    rests = [uj / ns * 1e3 for r, _ in data.values() for kind, uj, ns in r if kind == "idle" and ns > 1e9]
    p0 = st.median(rests)
    print("P_idle_session %.3f W (median of %d rests; min %.3f, max %.3f)" % (p0, len(rests), min(rests), max(rests)))
    out = os.path.join("results", "energy_summary_x86_session.csv")
    with open(out, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95",
                    "P_idle_session_W", "E_op_per_rest_uJ_mean", "E_op_per_rest_uJ_ci95", "P_rest_W_mean"])
        for f in sorted(files):
            rapl, ener = data[f]
            wins = [(uj, ns) for kind, uj, ns in rapl if kind == "window"]
            idles = [(uj, ns) for kind, uj, ns in rapl if kind == "idle"][1:]   # the rest after each window
            if not ener or len(wins) != len(ener):
                print("skip %s (windows %d, ENERGY rows %d)" % (f, len(wins), len(ener)))
                continue
            es, er, pr = [], [], []
            for i, ((uj, ns), e) in enumerate(zip(wins, ener)):
                n = int(e[7])
                pw = uj / ns * 1e3
                es.append((pw - p0) * ns / 1e9 / n * 1e6)
                if i < len(idles):
                    pi = idles[i][0] / idles[i][1] * 1e3
                    pr.append(pi)
                    er.append((pw - pi) * ns / 1e9 / n * 1e6)
            e0 = ener[0]
            w.writerow([e0[1], e0[2], e0[3], "x86:rapl_pkg", e0[5], len(es), "%.4f" % st.fmean(es), "%.4f" % ci(es), "%.3f" % p0,
                        "%.4f" % st.fmean(er), "%.4f" % ci(er), "%.3f" % st.fmean(pr)])
            print("%-8s %-8s session %12.2f +-%5.1f%%   per-rest %12.2f +-%5.1f%%   rest %.2f W" % (
                e0[1], e0[5], st.fmean(es), 100 * ci(es) / st.fmean(es), st.fmean(er),
                100 * ci(er) / st.fmean(er), st.fmean(pr)))
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1:])
