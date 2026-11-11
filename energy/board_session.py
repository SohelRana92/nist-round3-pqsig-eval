#!/usr/bin/env python3
"""board_session.py - energy per operation against one idle level for a
whole logger session (the board-level twin of rapl_session.py).

  python3 energy/board_session.py --label pi5 results/raw/energy/pi5_pmic

energy_analyze.py takes P_idle from the middle of the rest after each
window. After long or memory-heavy windows the board does not settle within
the rest (on the Pi 5, after SLH-DSA and FAEST signing, the rest stays
0.4-0.6 W above the usual 3.3 W, most likely the SoC still being warm), so
a per-rest P_idle hides part of the energy and widens the interval. Here
P_idle_session is the median of every rest in the session, and

    E_op = (P_window - P_idle_session) * T / N.

Writes results/energy_summary_<label>_session.csv (the per-rest value next
to it for comparison).
"""
import argparse
import csv
import glob
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import energy_analyze as ea  # noqa: E402

T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def ci(v):
    return T95.get(len(v) - 1, 1.96) * st.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("dir")
    a = ap.parse_args()
    runs = []
    for lg in sorted(glob.glob(os.path.join(a.dir, "*_log.csv"))):
        b = lg[:-8] + "_bench.csv"
        rows, _ = ea.analyse(list(csv.DictReader(open(lg))), list(csv.reader(open(b))))
        runs.append(rows)
    idle = [r["p_idle_W"] for rr in runs for r in rr]
    p0 = st.median(idle)
    print("P_idle_session %.3f W (median of %d rests; %.3f-%.3f)" % (p0, len(idle), min(idle), max(idle)))
    out = os.path.join("results", "energy_summary_%s_session.csv" % a.label)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95",
                    "P_idle_session_W", "E_op_per_rest_uJ_mean", "E_op_per_rest_uJ_ci95"])
        for rr in runs:
            for op in ("keypair", "sign", "verify"):
                ww = [r for r in rr if r["op"] == op]
                if not ww:
                    continue
                es = [(r["p_window_W"] - p0) * r["t_s"] / r["n_ops"] * 1e6 for r in ww]
                er = [r["E_op_uJ"] for r in ww]
                e = ww[0]["row"]
                w.writerow([e[1], e[2], e[3], a.label, op, len(es), "%.4f" % st.fmean(es), "%.4f" % ci(es),
                            "%.3f" % p0, "%.4f" % st.fmean(er), "%.4f" % ci(er)])
    print("wrote", out)


if __name__ == "__main__":
    main()
