#!/usr/bin/env python3
"""figs.py - Figs. 3, 4 and 5 of the paper as vector PDF files.

  python3 paper/scripts/figs.py  ->  paper/figures/Fig3, Fig4, Fig5 as .pdf and .png (600 dpi)

Fig. 3  results/summary_speed.csv: median signing and verification cycles,
        log scale, one panel per CPU platform.
Fig. 4  results/energy_*.csv: energy per signing and verification on three
        platforms, one row per scheme, log scale.
Fig. 5  results/raw/x86/batch_*.csv and results/raw/gpu/batch_*.csv:
        verifications per second against batch size, log-log axes.

Figures are drawn at the 5.15 in text width of the journal template, with all
text at 8 pt. Each series has its own colour and marker, so the figures also
read in greyscale.
"""
import csv
import glob
import os
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "paper", "figures")
DPI = 600   # resolution of the PNG copies
C = ["#2a78d6", "#eb6834", "#1baf7a"]
MARK = ["o", "s", "^"]
HATCH = ["", "////", "...."]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SCHEMES = ["FAEST", "MQOM", "SDitH", "UOV", "MAYO", "QR-UOV", "SNOVA", "SQIsign",
           "ML-DSA", "FN-DSA", "SLH-DSA", "Ed25519", "ECDSA"]
CPU = [("esp32", "ESP32"), ("microblaze", "MicroBlaze"), ("pi5", "Raspberry Pi 5"), ("x86", "Ryzen 9 9950X")]

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.linewidth": 0.6, "pdf.fonttype": 42,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
})

def save_png(fig, path):
    """PNG copy at DPI, saved as plain RGB on white (no transparency)."""
    from PIL import Image
    fig.savefig(path, dpi=DPI, facecolor="white")
    Image.open(path).convert("RGB").save(path, dpi=(DPI, DPI))



def rep_sets():
    import json
    return json.load(open(os.path.join(ROOT, "paper", "data", "representative_sets.json")))["sets"]


def rows(path):
    p = os.path.join(ROOT, path)
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []



def energy_rows(reader):
    """energy_summary.csv, with the x86 RAPL rows taken from
    energy_summary_x86_session.csv (one idle level per session, see
    energy/rapl_session.py) when that file exists."""
    import os as _os
    en = reader("results/energy_summary.csv") or []
    s = "results/energy_summary_x86_session.csv"
    if _os.path.exists(s):
        en = [r for r in en if not r["platform"].startswith("x86")] + (reader(s) or [])
    s2 = "results/energy_summary_pi5_session.csv"
    if _os.path.exists(s2):
        en = [r for r in en if r["platform"] != "pi5"] + (reader(s2) or [])
    v = "results/energy_microblaze_vivado.csv"
    if _os.path.exists(v):
        en = en + (reader(v) or [])
    return en

def fig3():
    sp = rows("results/summary_speed.csv")
    if not sp:
        print("fig3: results/summary_speed.csv missing; skipped")
        return
    rep = rep_sets()
    idx = {(r["scheme"], r["param"], r["variant"], r["platform"], r["op"]): float(r["median_cycles"])
           for r in sp if r["all_ok"] == "1"}
    fig, grid = plt.subplots(2, 2, figsize=(5.15, 4.3), sharex=True)
    axes = list(grid.flat)
    for i, (ax, (plat, name)) in enumerate(zip(axes, CPU)):
        xs = range(len(SCHEMES))
        for k, op in enumerate(("sign", "verify")):
            vals = []
            for s in SCHEMES:
                e = rep.get(s)
                var = e["variant"].get(plat, e["variant"].get("default")) if e else None
                vals.append(idx.get((s, e["param"], var, plat, op), 0) if e else 0)
            ax.bar([x + (k - 0.5) * 0.38 for x in xs], [v if v > 0 else float("nan") for v in vals],
                   width=0.36, color=C[k], hatch=HATCH[k], edgecolor="white", linewidth=0.4,
                   label="signing" if op == "sign" else "verification")
        ax.set_yscale("log")
        if i % 2 == 0:
            ax.set_ylabel("cycles")
        ax.set_title("(%s) %s" % ("abcd"[i], name), fontsize=8, loc="left", color=INK)
        ax.grid(axis="y", color=GRID, linewidth=0.4)
        ax.set_axisbelow(True)
    for ax in axes[2:]:
        ax.set_xticks(range(len(SCHEMES)))
        ax.set_xticklabels(SCHEMES, rotation=60, ha="right")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=2, fontsize=8)
    fig.tight_layout(h_pad=0.6, w_pad=0.8, rect=(0, 0, 1, 0.95))
    fig.savefig(os.path.join(OUT, "Fig3.pdf"))
    save_png(fig, os.path.join(OUT, "Fig3.png"))
    print("fig3 written")


def ratio_fmt(r):
    if r < 0.095:
        return "%.2f" % r
    if r < 0.95:
        return "%.1f" % r
    if r < 9.5:
        return "%.1f" % r if abs(r - round(r)) > 0.05 else "%d" % round(r)
    if r < 999.5:
        return "%d" % round(r)
    if r < 99500:
        return "%dk" % round(r / 1000) if r >= 9500 else "%.1fk" % (r / 1000)
    return "%.1fM" % (r / 1e6)


def fig4(joined=False, out_name="Fig4.pdf"):
    """Energy per operation on three platforms, one row per scheme, log scale:
    (a) signing, (b) verification. A grey bar spans the platforms of each
    scheme; rows are ordered by Pi 5 signing energy; the ML-DSA-44 row is
    shaded as the reference. joined=True also links each platform's markers
    across rows (preview only)."""
    en = energy_rows(rows)
    if not en:
        print("fig4: results/energy_summary.csv missing; skipped")
        return
    rep = rep_sets()
    idx = {(r["scheme"], r["param"], r["variant"], r["platform"], r["op"]): float(r["E_op_uJ_mean"]) for r in en}

    def E(s, plat, op):
        e = rep.get(s)
        pl = plat.split(":")[0]
        return idx.get((s, e["param"], e["variant"].get(pl, e["variant"].get("default")), plat, op))

    plats = [("microblaze:vivado", "MicroBlaze (estimate)", "o", "#0072B2"),
             ("pi5", "Raspberry Pi 5 (PMIC)", "s", "#D55E00"),
             ("x86:rapl_pkg", "Ryzen 9 9950X (RAPL)", "^", "#009E73")]
    order = sorted(SCHEMES, key=lambda s: E(s, "pi5", "sign") or 0)
    fig, axes = plt.subplots(1, 2, figsize=(5.15, 3.5), sharey=True)
    for ax, op, title in zip(axes, ("sign", "verify"), ("(a) Signing", "(b) Verification")):
        r_ml = order.index("ML-DSA")
        ax.axhspan(r_ml - 0.45, r_ml + 0.45, color="#f1efe9", zorder=0)
        for i, s in enumerate(order):
            xs = [E(s, p, op) for p, *_ in plats if E(s, p, op)]
            if xs:
                ax.plot([min(xs), max(xs)], [i, i], color="#cfcfcf", lw=2.4, zorder=1, solid_capstyle="round")
        for p, lab, m, c in plats:
            pts = [(E(s, p, op), i) for i, s in enumerate(order) if E(s, p, op)]
            ax.scatter([x for x, _ in pts], [y for _, y in pts], marker=m, color=c, s=26, zorder=3,
                       label=lab, edgecolor="white", linewidth=0.4)
            if joined:
                ax.plot([x for x, _ in pts], [y for _, y in pts], color=c, lw=0.8, alpha=0.7, zorder=2)
        ax.set_xscale("log")
        ax.set_xlabel(r"energy per operation ($\mu$J)")
        ax.set_title(title, fontsize=8, loc="left", color=INK)
        ax.grid(axis="x", color=GRID, linewidth=0.4)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(range(len(order)))
    axes[0].set_yticklabels(order)
    for t, s in zip(axes[0].get_yticklabels(), order):
        t.set_fontweight("bold" if s in SCHEMES[:8] else "normal")
        t.set_color(INK if s in SCHEMES[:8] else INK2)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=3, fontsize=8, handletextpad=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.92), w_pad=1.0)
    fig.savefig(os.path.join(OUT, out_name))
    save_png(fig, os.path.join(OUT, out_name.replace(".pdf", ".png")))
    print("fig4 written", out_name)


def batch_rates(path, device):
    """{batch: verifies/s}, shared-key mode, as in Table VIII (make_tables.py):
    CPU from the BATCH rows; GPU end to end, kernel median plus the
    host-device copies of the GPU_XFER row. Repetitions with all_ok=0 dropped."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return {}
    ns, xfer = {}, {}
    for r in csv.reader(open(full)):
        if not r:
            continue
        if r[0] == "BATCH" and r[5] == device and r[6] == "shared" and r[-1] == "1":
            ns.setdefault(int(r[8]), []).append(float(r[10]))
        elif r[0] == "GPU_XFER" and r[4] == "shared":
            xfer[int(r[5])] = float(r[6]) + float(r[7])
    return {b: b / ((st.median(v) + (xfer.get(b, 0.0) if device == "gpu" else 0.0)) / 1e9)
            for b, v in ns.items()}


# Okabe-Ito colours for the eight candidates; baselines in greys, dashed
CAND_C = ["#000000", "#E69F00", "#56B4E9", "#009E73", "#D55E00", "#0072B2", "#CC79A7", "#F0E442"]
CAND_M = ["o", "s", "^", "D", "v", "P", "X", "*"]
BASE_C = ["#3d3d3d", "#8c8c8c", "#5e5e5e", "#262626", "#a8a8a8"]
BASE_M = ["o", "s", "^", "D", "v"]


def fig5():
    import json
    rep = rep_sets()
    recipes = json.load(open(os.path.join(ROOT, "registry", "recipes.json")))["recipes"]
    series = []
    for i, s in enumerate(SCHEMES):
        e = rep.get(s)
        if not e:
            continue
        var = e["variant"].get("x86", e["variant"].get("default"))
        cpu_rec = next((n for n, v in recipes.items() if v["scheme"] == s and v["param"] == e["param"] and v["variant"] == var), None)
        cpu = batch_rates("results/raw/x86/batch_%s.csv" % cpu_rec, "cpu") if cpu_rec else {}
        gpu = batch_rates("results/raw/gpu/batch_%s.csv" % e["recipe_gpu"], "gpu") if e.get("recipe_gpu") else {}
        cand = i < 8
        style = dict(color=CAND_C[i] if cand else BASE_C[i - 8], marker=CAND_M[i] if cand else BASE_M[i - 8],
                     ls="-" if cand else "--", lw=1.3 if cand else 1.0, ms=4)
        series.append((s, cpu, gpu, style))
    if not any(c for _, c, _, _ in series):
        print("fig5: no CPU batch files; skipped")
        return
    fig = plt.figure(figsize=(5.15, 4.6))
    a0 = fig.add_subplot(2, 2, 1)
    axes = [a0, fig.add_subplot(2, 2, 2, sharey=a0), fig.add_subplot(2, 2, 3)]
    lax = fig.add_subplot(2, 2, 4)
    lax.axis("off")
    titles = ["(a) CPU, 32 threads", "(b) GPU, RTX 5070 Ti", "(c) GPU / CPU ratio"]
    for s, cpu, gpu, sty in series:
        for ax, d in ((axes[0], cpu), (axes[1], gpu)):
            if d:
                xs = sorted(d)
                ax.plot(xs, [d[x] for x in xs], label=s, **sty)
        common = sorted(set(cpu) & set(gpu))
        if common:
            axes[2].plot(common, [gpu[b] / cpu[b] for b in common], label=s, **sty)
    for k, ax in enumerate(axes):
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("batch size")
        ax.set_title(titles[k], fontsize=8, loc="left", color=INK)
        ax.grid(color=GRID, linewidth=0.4)
        ax.set_axisbelow(True)
    axes[1].tick_params(labelleft=False)
    axes[0].set_ylabel("verifications/s")
    axes[2].set_ylabel("GPU rate / CPU rate")
    axes[2].axhline(1.0, color=INK, lw=0.8, ls=":")
    axes[2].text(1.3, 1.15, "GPU faster above", fontsize=8, color=INK2, va="bottom")
    h, l = axes[0].get_legend_handles_labels()
    lax.legend(h, l, loc="center", ncol=2, fontsize=8, handlelength=2.6, columnspacing=1.2, frameon=False)
    fig.tight_layout(h_pad=1.0, w_pad=1.0)
    fig.savefig(os.path.join(OUT, "Fig5.pdf"))
    save_png(fig, os.path.join(OUT, "Fig5.png"))
    print("fig5 written")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fig3()
    fig4()
    fig5()
