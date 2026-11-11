#!/usr/bin/env python3
"""rapl_analyze.py - energy per operation on the Ryzen 9 9950X from the
RAPL lines that the harness prints when HARNESS_RAPL is set.

Run on the 9950X (energy_uj is root-readable only):
  sudo HARNESS_RAPL=/sys/class/powercap/intel-rapl:0/energy_uj \\
       taskset -c 2 build/x86/<recipe>/bench energy sign 10 5 > rapl_sign.csv
  energy/rapl_analyze.py rapl_sign.csv

For window w the harness prints, in order:
  RAPL,idle,<uJ>,<ns>     the rest before the window (the first one is short)
  RAPL,window,<uJ>,<ns>   the window itself
  ENERGY,...,op,w,<ops>,<window_ns>
Each rest is a sleep: 1 s to settle (not counted), then 2 s that give the
RAPL,idle row. P_idle for window w is the mean power of the rest that FOLLOWS it (the
RAPL,idle line printed when window w+1 starts), the same rule that
energy_analyze.py uses for the external sensors. The last window has no
following rest, so it uses the rest before it.

  E_op = (E_window - P_idle * T_window) / N_ops

RAPL measures the whole package, so P_idle includes every background
process. The paper states this.
Appends one row to results/energy_summary.csv with platform x86 and the
sensor name rapl_pkg.
"""
import csv
import math
import os
import statistics as st
import sys

T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
       8: 2.306, 9: 2.262, 10: 2.228}


def main(path):
    idle, win, ener = [], [], []
    for row in csv.reader(open(path)):
        if not row:
            continue
        if row[0] == "RAPL" and row[1] == "idle":
            idle.append((int(row[2]), int(row[3])))
        elif row[0] == "RAPL" and row[1] == "window":
            win.append((int(row[2]), int(row[3])))
        elif row[0] == "ENERGY":
            ener.append(row)
    if not win or len(win) != len(ener):
        sys.exit("found %d RAPL windows and %d ENERGY lines" % (len(win), len(ener)))
    # idle[0] is the stretch from start-up to window 0; idle[k] (k>=1) is the
    # rest after window k-1.
    rests = idle[1:] or idle[:1]
    vals = []
    for k, ((e_uj, t_ns), e) in enumerate(zip(win, ener)):
        r = rests[k] if k < len(rests) else rests[-1]
        p_idle_w = r[0] * 1e-6 / (r[1] * 1e-9)
        n_ops = int(e[7])
        e_op = (e_uj * 1e-6 - p_idle_w * t_ns * 1e-9) / n_ops * 1e6
        vals.append(e_op)
        print("window %d  ops %d  T %.3f s  P_win %.3f W  P_idle %.3f W  E_op %.3f uJ"
              % (k, n_ops, t_ns / 1e9, e_uj * 1e-6 / (t_ns * 1e-9), p_idle_w, e_op))
    m = st.fmean(vals)
    h = T95.get(len(vals) - 1, 1.96) * st.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else float("nan")
    print("E_op mean %.3f uJ, 95%% CI +- %.3f uJ, n=%d windows" % (m, h, len(vals)))
    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "energy_summary.csv")
    new = not os.path.exists(out)
    with open(out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95"])
        e0 = ener[0]
        w.writerow([e0[1], e0[2], e0[3], e0[4] + ":rapl_pkg", e0[5], len(vals), "%.4f" % m, "%.4f" % h])


if __name__ == "__main__":
    main(sys.argv[1])
