#!/usr/bin/env python3
"""fig_hierarchy.py - Fig. 1 of the paper: the IoT hierarchy the five platforms stand for.

  python3 paper/scripts/fig_hierarchy.py      ->  paper/figures/fig0_hierarchy.pdf

Pure matplotlib, vector output, all text 8 pt or larger. Every platform fact
in the boxes is taken from the platform table (paper/tables/tab3_platforms.tex in the manuscript). The links
carry what the paper computes for them (frames, certificate bytes); no
network traffic was measured, and the figure does not claim any.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "paper", "figures", "fig0_hierarchy.pdf")

INK, INK2, EDGE = "#000000", "#333333", "#000000"
TIER_FILL = ["#ffffff", "#f2f2f2", "#e3e3e3"]   # white to light grey, darker = higher tier
TIER_LINE = ["#000000", "#000000", "#000000"]
FPGA_FILL, FPGA_LINE = "#ffffff", "#000000"

plt.rcParams.update({"font.family": "serif", "font.size": 8, "pdf.fonttype": 42})

W, H = 7.16, 2.9
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 100)
ax.set_ylim(0, 40)
ax.axis("off")

# x position and width of the three tier boxes; the gaps carry the links
BX = [(1.0, 24.0), (38.5, 24.0), (75.5, 23.5)]
BY, BH = 14.0, 24.5

tiers = [
    ("Tier 1: sensor node", ["ESP32"],
     ["Xtensa LX6, 240 MHz", "520 KB SRAM, no PSRAM"],
     ["signs readings,", "verifies firmware"],
     "RQ1 fit; RQ2 cycles, stack"),
    ("Tier 2: edge gateway", ["Raspberry Pi 5"],
     ["4x Cortex-A76, 2.4 GHz", "8 GB RAM"],
     ["verifies many nodes,", "forwards upstream"],
     "RQ2 energy; RQ3 timing"),
    ("Tier 3: server", ["Ryzen 9 9950X", "+ RTX 5070 Ti GPU"],
     ["16 cores, 32 threads", "GPU: 70 SMs, 16 GB"],
     ["verifies fleet traffic", "in batches"],
     "RQ2, RQ3; RQ4 batch rate"),
]

for k, ((x, w), (tier, plat, spec, role, rq)) in enumerate(zip(BX, tiers)):
    ax.add_patch(FancyBboxPatch((x, BY), w, BH, boxstyle="round,pad=0.25,rounding_size=1.2",
                                fc=TIER_FILL[k], ec=TIER_LINE[k], lw=1.8))
    cx = x + w / 2
    top = BY + BH
    ax.text(cx, top - 2.0, tier, ha="center", va="center", fontsize=8.5, color=TIER_LINE[k], weight="bold")
    if len(plat) == 1:
        ax.text(cx, top - 5.3, plat[0], ha="center", va="center", fontsize=9, color=INK, weight="bold")
    else:
        ax.text(cx, top - 4.6, plat[0], ha="center", va="center", fontsize=9, color=INK, weight="bold")
        ax.text(cx, top - 7.0, plat[1], ha="center", va="center", fontsize=8, color=INK, weight="bold")
    ax.text(cx, top - 9.6, spec[0], ha="center", va="center", color=INK2)
    ax.text(cx, top - 12.0, spec[1], ha="center", va="center", color=INK2)
    ax.plot([x + 2, x + w - 2], [top - 14.0] * 2, color="#000000", lw=0.6)
    ax.text(cx, top - 16.1, role[0], ha="center", va="center", color=INK, style="italic")
    ax.text(cx, top - 18.5, role[1], ha="center", va="center", color=INK, style="italic")
    ax.text(cx, BY + 1.9, rq, ha="center", va="center", color=INK)

# links between tiers: two-headed arrows, labelled with what the paper computes for them
links = [
    (BX[0][0] + BX[0][1], BX[1][0], "802.15.4 / BLE", ["key, signature", "frames (RQ5)"]),
    (BX[1][0] + BX[1][1], BX[2][0], "IP backhaul", ["certificate", "chain (RQ5)"]),
]
for x0, x1, head, sub in links:
    yy = BY + BH / 2 + 1.5
    ax.add_patch(FancyArrowPatch((x0 + 0.8, yy), (x1 - 0.8, yy), arrowstyle="<|-|>", mutation_scale=10,
                                 lw=1.6, color="#000000"))
    xm = (x0 + x1) / 2
    ax.text(xm, yy + 2.4, head, ha="center", va="center", fontsize=8, color=INK)
    ax.text(xm, yy - 2.5, sub[0], ha="center", va="center", fontsize=8, color=INK2)
    ax.text(xm, yy - 4.9, sub[1], ha="center", va="center", fontsize=8, color=INK2)

# custom silicon: FPGA soft core, a side path below tier 1
fx, fw, fy, fh = 1.0, 35.0, 1.0, 9.6
ax.add_patch(FancyBboxPatch((fx, fy), fw, fh, boxstyle="round,pad=0.25,rounding_size=1.2",
                            fc=FPGA_FILL, ec=FPGA_LINE, lw=1.8, ls=(0, (5, 2))))
ax.text(fx + fw / 2, fy + fh - 1.9, "Custom silicon", ha="center", va="center", fontsize=8.5,
        weight="bold", color=INK)
ax.text(fx + fw / 2, fy + fh - 4.4, "MicroBlaze on a Spartan-7, 81 MHz", ha="center", va="center",
        color=INK2)
ax.text(fx + fw / 2, fy + 1.8, "RQ1 fit; RQ2 cycles, code size, energy est.", ha="center", va="center",
        color=INK)
tier1_cx = BX[0][0] + BX[0][1] / 2
ax.add_patch(FancyArrowPatch((tier1_cx, fy + fh + 0.4), (tier1_cx, BY - 0.5), arrowstyle="-",
                             lw=1.4, color=FPGA_LINE, ls=(0, (3, 2))))

# common method band
mx, mw = 38.5, 60.5
ax.add_patch(FancyBboxPatch((mx, fy), mw, fh, boxstyle="round,pad=0.25,rounding_size=1.2",
                            fc="white", ec=EDGE, lw=1.8))
ax.text(mx + mw / 2, fy + fh - 1.9, "One benchmark framework on every tier", ha="center", va="center",
        fontsize=8.5, weight="bold", color=INK)
ax.text(mx + mw / 2, fy + fh - 4.4, "8 Round-3 candidates and 6 baselines, same code on every platform",
        ha="center", va="center", color=INK2)
ax.text(mx + mw / 2, fy + 1.8, "known-answer test passes before any timing, energy or batch run",
        ha="center", va="center", color=INK2)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
fig.savefig(OUT)
print("written", OUT)
