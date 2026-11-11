#!/usr/bin/env python3
"""vivado_estimate.py - estimated energy per operation on the MicroBlaze
from the Vivado power report and the measured operation times.

  python3 energy/vivado_estimate.py      # reads results/fpga/power.rpt, results/summary_speed.csv

E_op = P_chip x t_op, with P_chip the total on-chip power of the
implemented design (static + dynamic) from report_power, and t_op the
median time of the operation. It is an estimate: report_power runs without
switching-activity data (vectorless, confidence "Low") and covers the FPGA
only, not the DDR3 memory or the rest of the Arty S7 board. Rows go to
results/energy_microblaze_vivado.csv with platform microblaze:vivado.
"""
import csv
import os
import re

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    rpt = open(os.path.join(TOP, "results", "fpga", "power.rpt")).read()
    p = float(re.search(r"Total On-Chip Power \(W\)\s*\|\s*([0-9.]+)", rpt).group(1))
    dyn = float(re.search(r"Dynamic \(W\)\s*\|\s*([0-9.]+)", rpt).group(1))
    conf = re.search(r"Confidence Level\s*\|\s*(\w+)", rpt).group(1)
    out = os.path.join(TOP, "results", "energy_microblaze_vivado.csv")
    n = 0
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "variant", "platform", "op", "windows", "E_op_uJ_mean", "E_op_uJ_ci95",
                    "P_chip_W", "P_dynamic_W", "confidence", "t_op_ns"])
        for r in csv.DictReader(open(os.path.join(TOP, "results", "summary_speed.csv"))):
            if r["platform"] != "microblaze" or r["op"] not in ("keypair", "sign", "verify"):
                continue
            t = float(r["median_ns"])
            w.writerow([r["scheme"], r["param"], r["variant"], "microblaze:vivado", r["op"], "", "%.4f" % (p * t / 1e3),
                        "", p, dyn, conf, "%.0f" % t])
            n += 1
    print("P_chip %.3f W (dynamic %.3f W, confidence %s); %d rows -> %s" % (p, dyn, conf, n, out))


if __name__ == "__main__":
    main()
