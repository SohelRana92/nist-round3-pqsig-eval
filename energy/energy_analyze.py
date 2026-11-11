#!/usr/bin/env python3
"""energy_analyze.py - energy per operation from a logger CSV and the
board's harness output.

  E_op = (P_window - P_idle) * T_window / N_ops

P_window: mean power while the marker is high.
P_idle:   mean power in the middle half of each 2 s rest that follows a
          window (marker low), which leaves out switching transients.
T_window, N_ops: from the board's ENERGY line for the same window index.

Usage:
  energy/energy_analyze.py --log esp32_sign_log.csv --bench esp32_sign_bench.csv
Prints one row per window and the mean with a 95% confidence interval
(Student t), and appends a summary row to results/energy_summary.csv.

Self-test with synthetic data (no hardware needed):
  energy/energy_analyze.py --selftest
"""
import argparse
import csv
import math
import os
import statistics as st
import sys

T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
       8: 2.306, 9: 2.262, 10: 2.228}


def windows(rows):
    """Split samples into (high_segment, following_low_segment) pairs."""
    segs = []
    cur, val = [], None
    for r in rows:
        m = int(r["marker"])
        if val is None or m == val:
            cur.append(r)
        else:
            segs.append((val, cur))
            cur = [r]
        val = m
    if cur:
        segs.append((val, cur))
    pairs = []
    for i, (v, s) in enumerate(segs):
        if v == 1:
            low = segs[i + 1][1] if i + 1 < len(segs) and segs[i + 1][0] == 0 else []
            pairs.append((s, low))
    return pairs


def mean_power(samples):
    return st.fmean(float(r["power_W"]) for r in samples)


def analyse(log_rows, bench_rows):
    pairs = windows(log_rows)
    ener = [r for r in bench_rows if r and r[0] == "ENERGY"]
    if len(pairs) != len(ener):
        sys.exit("logger saw %d windows, board printed %d ENERGY lines" % (len(pairs), len(ener)))
    out = []
    for (hi, lo), e in zip(pairs, ener):
        n_ops = int(e[7])
        t_s = int(e[8]) / 1e9
        mid = lo[len(lo) // 4: 3 * len(lo) // 4] or lo
        p_w = mean_power(hi)
        p_i = mean_power(mid) if mid else float("nan")
        e_uj = (p_w - p_i) * t_s / n_ops * 1e6 if n_ops else float("nan")
        # the logger's high segment and the board's own window time must agree
        t_hi = (int(hi[-1]["t_ns"]) - int(hi[0]["t_ns"])) / 1e9 if len(hi) > 1 else 0.0
        ok = abs(t_hi - t_s) <= max(0.5, 0.05 * t_s)
        e_tot = p_w * t_s / n_ops * 1e6 if n_ops else float("nan")
        out.append({"window": int(e[6]), "op": e[5], "n_ops": n_ops, "t_s": t_s, "t_marker_s": t_hi,
                    "match": "ok" if ok else "MISMATCH",
                    "p_window_W": p_w, "p_idle_W": p_i, "E_op_uJ": e_uj, "E_total_uJ": e_tot,
                    "samples": len(hi), "row": e})
    return out, ener[0]


def summary(rows, key="E_op_uJ"):
    v = [r[key] for r in rows]
    m = st.fmean(v)
    if len(v) > 1:
        half = T95.get(len(v) - 1, 1.96) * st.stdev(v) / math.sqrt(len(v))
    else:
        half = float("nan")
    return m, half


def selftest():
    # 5 windows of 10 s at 1.20 W over a 0.80 W idle, 400 ops per window:
    # E_op = 0.40 W * 10 s / 400 = 10 mJ = 10000 uJ.
    log, bench = [], [["ENERGY_HDR"]]
    t = 0
    for w in range(5):
        for _ in range(1000):
            log.append({"t_ns": t, "power_W": "1.20", "marker": "1"}); t += 10_000_000
        for _ in range(200):
            log.append({"t_ns": t, "power_W": "0.80", "marker": "0"}); t += 10_000_000
        bench.append(["ENERGY", "X", "p", "ref", "esp32", "sign", str(w), "400", "10000000000"])
    rows, _ = analyse(log, bench)
    m, h = summary(rows)
    ok = abs(m - 10000.0) < 1e-6
    print("selftest: E_op = %.3f uJ (expected 10000.000): %s" % (m, "pass" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log")
    ap.add_argument("--bench")
    ap.add_argument("--label", default="", help="platform label in the summary, e.g. pi5:ina219")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    log_rows = list(csv.DictReader(open(a.log)))
    bench_rows = list(csv.reader(open(a.bench)))
    rows, e0 = analyse(log_rows, bench_rows)
    for r in rows:
        print("%(op)-8s window %(window)d  ops %(n_ops)d  T %(t_s).3f s (marker %(t_marker_s).3f s, %(match)s)  "
              "P_win %(p_window_W).4f W  P_idle %(p_idle_W).4f W  E_op %(E_op_uJ).3f uJ  "
              "E_total %(E_total_uJ).3f uJ  (%(samples)d samples)" % r)
    os.makedirs("results", exist_ok=True)
    path = os.path.join("results", "energy_summary.csv")
    board = os.path.join("results", "energy_board.csv")
    bad = sum(r["match"] != "ok" for r in rows)
    # One summary row per operation; a log can hold several operations in
    # the order the board ran them.
    ops = []
    for r in rows:
        if r["op"] not in ops:
            ops.append(r["op"])
    for op in ops:
        rr = [r for r in rows if r["op"] == op]
        e = rr[0]["row"]
        m, h = summary(rr)
        mt, ht = summary(rr, "E_total_uJ")
        label = a.label or e[4]
        print("%-8s E_op mean %.3f uJ, 95%% CI +- %.3f uJ; E_total mean %.3f uJ; n=%d windows"
              % (op, m, h, mt, len(rr)))
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95"])
            w.writerow([e[1], e[2], e[3], label, op, len(rr), "%.4f" % m, "%.4f" % h])
        new = not os.path.exists(board)
        with open(board, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95",
                            "E_total_uJ_mean", "E_total_uJ_ci95", "P_idle_W_mean", "P_window_W_mean",
                            "ops_per_window_mean", "marker_mismatch_windows"])
            w.writerow([e[1], e[2], e[3], label, op, len(rr), "%.4f" % m, "%.4f" % h, "%.4f" % mt, "%.4f" % ht,
                        "%.5f" % st.fmean(r["p_idle_W"] for r in rr), "%.5f" % st.fmean(r["p_window_W"] for r in rr),
                        "%.1f" % st.fmean(r["n_ops"] for r in rr), sum(r["match"] != "ok" for r in rr)])
    if bad:
        print("WARNING: %d windows where the marker time and the board's window time differ by over 5%%" % bad)


if __name__ == "__main__":
    main()
