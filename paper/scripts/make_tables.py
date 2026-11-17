#!/usr/bin/env python3
"""make_tables.py - write the LaTeX tables of the paper from the CSV files.

  python3 paper/scripts/make_tables.py

Reads (paths relative to the repository root):
  paper/data/sizes_from_api.csv      pk/sk/sig bytes from each package's api.h
  paper/data/representative_sets.json       which Category 1 set represents each scheme
  results/summary_speed.csv                 tools/summarize.py
  results/summary_stack.csv, summary_code.csv
  results/energy_summary.csv                energy/energy_analyze.py, energy/rapl_analyze.py
  results/feasibility.csv                   tools/esp32_feasibility.py, tools/gpu_feasibility.py
  results/ct_<platform>.csv                 ct/run_ct.sh

Writes paper/tables/tab_*.tex. A missing value stops the script with an
error that names the file it should come from.
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = os.path.join(ROOT, "paper")
R = os.path.join(ROOT, "results")
OUT = os.path.join(P, "tables")

SCHEMES = ["FAEST", "MQOM", "SDitH", "UOV", "MAYO", "QR-UOV", "SNOVA", "SQIsign"]
BASE = ["ML-DSA", "FN-DSA", "SLH-DSA", "Ed25519", "ECDSA"]
FAMILY = {
    "FAEST": ("VOLE-in-the-head", "AES as a one-way function"),
    "MQOM": ("MPC-in-the-head", "MQ equations"),
    "SDitH": ("VOLE-in-the-head", "Syndrome decoding"),
    "UOV": ("Multivariate", "Unbalanced Oil and Vinegar"),
    "MAYO": ("Multivariate", "Whipped UOV"),
    "QR-UOV": ("Multivariate", "UOV over a quotient ring"),
    "SNOVA": ("Multivariate", "UOV over a matrix ring"),
    "SQIsign": ("Isogeny", "Endomorphism ring problem"),
    "ML-DSA": ("Lattice", "Module-LWE and SIS"),
    "FN-DSA": ("Lattice", "NTRU lattices"),
    "SLH-DSA": ("Hash-based", "Hash function security"),
    "Ed25519": ("Elliptic curve", "ECDLP"),
    "ECDSA": ("Elliptic curve", "ECDLP"),
}
CPU_PLATS = [("esp32", "ESP32"), ("microblaze", "MicroBlaze"), ("pi5", "Pi 5"), ("x86", "9950X")]


def esc(s):
    return s.replace("_", r"\_")


def missing(src):
    """A table cell without a value: stop and name the file that fills it."""
    raise SystemExit("missing value in a table; check %s" % src)


def read_csv(path):
    p = os.path.join(ROOT, path)
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []



def energy_rows(reader):
    """energy_summary.csv, with the x86 RAPL rows taken from
    energy_summary_x86_session.csv (one idle level per session, see
    energy/rapl_session.py) when that file exists."""
    import os as _os
    en = reader("results/energy_summary.csv") or []
    s = "results/energy_summary_x86_session.csv"
    if _os.path.exists(_os.path.join(ROOT, s)):
        en = [r for r in en if not r["platform"].startswith("x86")] + (reader(s) or [])
    s2 = "results/energy_summary_pi5_session.csv"
    if _os.path.exists(_os.path.join(ROOT, s2)):
        en = [r for r in en if r["platform"] != "pi5"] + (reader(s2) or [])
    v = "results/energy_microblaze_vivado.csv"
    if _os.path.exists(_os.path.join(ROOT, v)):
        en = en + (reader(v) or [])
    return en

def kfmt(x):
    """cycles -> kilocycles with three significant figures"""
    v = float(x) / 1e3
    if v >= 100:
        return "{:,.0f}".format(v)
    if v >= 10:
        return "%.1f" % v
    return "%.2f" % v




# Captions and notes of the tables as printed in the paper. write() puts
# these in place of the working captions below.
CAPTIONS = {
    "tab_sizes.tex": (r"The eight Round-3 candidates and six baselines, with sizes in bytes for every Category~1 parameter set.",
                       r"Sizes are read from each package's \texttt{api.h} through our framework \texttt{sizes} command."),
    "tab_feasibility.tex": (r"Which schemes run on each platform, with the limiting resource named when one does not.", ""),
    "tab_cycles.tex": (r"Median kilocycles for key generation, signing and verification in Category~1 on four CPU platforms.",
                        r"KG: key generation; S: signing; V: verification. ESP32 and MicroBlaze run portable C; the Pi~5 and the 9950X run the submitters' optimised code where it exists. 1{,}000 runs after 10 warm-up runs, or 100 when one operation takes more than 1~s. A dash marks a set that does not run (Table~\ref{tab:feasibility}). On the ESP32, SNOVA uses the memory-saving build."),
    "tab_memory_energy.tex": (r"Peak stack, code size and energy per signature for the representative set of each scheme.",
                               r"Stack and code (MB: MicroBlaze) in bytes. $^{\mathrm{a}}$Vivado estimate, not a measurement."),
    "tab_ct_x86.tex": (r"Constant-time test results for signing on the Ryzen~9 9950X, with one row per tested build.",
                    r"$|t|$: largest Welch statistic of the fixed-versus-random test. Control: both classes sign with the same key. Confirm: a second run with a new seed. Leak: $|t|>4.5$ in both runs with the control below 4.5; inconclusive: control above 4.5; not repeated: only the first run above 4.5. Memcheck: reports with the secret key marked undefined, capped at 1{,}000; n/a: Valgrind~3.22 cannot decode GFNI or AVX-512. $^{\mathrm{a}}$Key copied into a random slot before every measurement."),
    "tab_ct_pi5.tex": (r"Constant-time test results for signing on the Raspberry Pi~5, under the same rules as Table~\ref{tab:ct}.",
                         r"Three tests run in parallel on cores 1 to 3. A one-hour budget per test sets $n$, so slow signers get fewer measurements than on the 9950X. Valgrind~3.22 decodes the NEON code. $^{\mathrm{a}}$Key copied into a random slot before every measurement."),
    "tab_batch.tex": (r"Batch verification throughput on the 9950X and the RTX~5070~Ti, and where the GPU overtakes the CPU.",
                       r"Verifications per second, shared-key mode. CPU: 32 threads, recipe of Table~\ref{tab:cycles}. GPU: portable recipe, one thread per signature, end to end with copies. Cross.: smallest batch at which the GPU is faster. A dash marks no correct GPU result (Table~\ref{tab:feasibility}); t/o: one run would exceed 40 minutes. SNOVA uses SNOVA\_I\_K with AES on the GPU, because the SHAKE versions reject every valid signature there."),
    "tab_message.tex": (r"Frames per signed 64-byte reading on three IoT links, and the size of a three-certificate chain.",
                         r"$^{\mathrm{a}}$Chain measured directly; the other chains are computed."),
}


def _swap_caption(body, short, note):
    i = body.find("\\caption{")
    if i < 0:
        return body
    j, depth = i + len("\\caption{"), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(body[j], 0)
        j += 1
    body = body[:i] + "\\caption{" + short + "}" + body[j:]
    if note:
        k = body.rfind("\\end{tabular}")
        k = body.find("\n", k) + 1
        body = body[:k] + "\\footnotetext{" + note + "}\n" + body[k:]
    return body


def write(name, body):
    os.makedirs(OUT, exist_ok=True)
    if name in CAPTIONS:
        body = _swap_caption(body, *CAPTIONS[name])
    with open(os.path.join(OUT, name), "w") as f:
        f.write(body)


def table1():
    rows = read_csv("paper/data/sizes_from_api.csv")
    by = {}
    for r in rows:
        by.setdefault(r["scheme"], []).append(r)
    lines = []
    for s in SCHEMES + BASE:
        rs = by.get(s, [])
        fam, hard = FAMILY[s]
        first = True
        for r in rs:
            lines.append("%s & %s & %s & %s & %s & %s & %s \\\\" % (
                s if first else "", fam if first else "", hard if first else "",
                esc(r["param"]), "{:,}".format(int(r["pk_bytes"])), "{:,}".format(int(r["sk_bytes"])),
                "{:,}".format(int(r["sig_bytes"]))))
            first = False
        if not rs:
            lines.append("%s & %s & %s & %s & & & \\\\" % (s, fam, hard, missing("api.h")))
        lines.append(r"\midrule")
    if lines and lines[-1] == r"\midrule":
        lines.pop()
    write("tab_sizes.tex", r"""\begin{table}[!htbp]
\caption{The eight Round-3 candidates and six baselines with every Category~1 parameter set. Sizes in bytes, read from each package's \texttt{api.h} through our framework \texttt{sizes} command.}
\label{tab:sizes}
\centering
\footnotesize
\begin{tabular}{lllrrrr}
\toprule
Scheme & Family & Hardness basis & Parameter set & pk & sk & sig \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def representative():
    p = os.path.join(P, "data", "representative_sets.json")
    return json.load(open(p))


def no_run(plat):
    """(scheme, param, variant) of recipes that do not run on a board, from
    tools/esp32_feasibility.py. Their cells show a dash, not a to-do mark."""
    out = set()
    for r in read_csv("results/feasibility_sets_%s.csv" % plat):
        if r["status"] != "runs":
            out.add((r["scheme"], r["param"], r["variant"]))
    return out


DASH = "--"


def table5():
    rep = representative()
    nr = {p: no_run(p) for p, _ in CPU_PLATS}
    speed = read_csv("results/summary_speed.csv")
    idx = {}
    for r in speed:
        if r["all_ok"] != "1":
            continue
        idx[(r["scheme"], r["param"], r["variant"], r["platform"], r["op"])] = r
    lines = []
    for s in SCHEMES + BASE:
        e = rep["sets"].get(s)
        if not e:
            continue
        cells = []
        for plat, _ in CPU_PLATS:
            var = e["variant"].get(plat, e["variant"].get("default"))
            for op in ("keypair", "sign", "verify"):
                r = idx.get((s, e["param"], var, plat, op))
                if r:
                    cells.append(kfmt(r["median_cycles"]))
                elif (s, e["param"], var) in nr[plat] or (s == "SDitH" and plat in ("esp32", "microblaze")):
                    cells.append(DASH)
                else:
                    cells.append(missing("speed"))
        lines.append("%s & %s & %s \\\\" % (s, esc(e["param"]), " & ".join(cells)))
    head = " & ".join(r"\multicolumn{3}{c}{%s}" % n for _, n in CPU_PLATS)
    cm = " ".join(r"\cmidrule(lr){%d-%d}" % (3 + 3 * i, 5 + 3 * i) for i in range(len(CPU_PLATS)))
    write("tab_cycles.tex", r"""\begin{table}[!htbp]
\caption{Median kilocycles for key generation (KG), signing (S) and verification (V), Category~1. Portable reference C on ESP32 and MicroBlaze; the submitters' optimised code on the Pi~5 and the 9950X where it exists, reference C otherwise. 1{,}000 runs after 10 warm-up runs, or 100 runs when one operation takes more than 1~s. A dash marks a set that does not run on that platform (Table~\ref{tab:feasibility}). On the ESP32, SNOVA uses the submitters' memory-saving variant.}
\label{tab:cycles}
\centering
\scriptsize
\setlength{\tabcolsep}{3pt}
\begin{tabular}{ll""" + "rrr" * len(CPU_PLATS) + r"""}
\toprule
 & & """ + head + r""" \\
""" + cm + r"""
Scheme & Set & """ + " & ".join(["KG & S & V"] * len(CPU_PLATS)) + r""" \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def table6():
    recipes_all = json.load(open(os.path.join(ROOT, "registry", "recipes.json")))["recipes"]
    rep = representative()
    stack = read_csv("results/summary_stack.csv")
    code = read_csv("results/summary_code.csv")
    en = energy_rows(read_csv)
    st = {(r["scheme"], r["param"], r["variant"], r["platform"], r["op"]): r for r in stack if r.get("ok") == "1"}
    nr = {p: no_run(p) for p in ("esp32", "pi5")}
    cd = {(r["recipe"], r["platform"]): r for r in code}
    ee = {(r["scheme"], r["param"], r["variant"], r["platform"], r["op"]): r for r in en}
    lines = []
    for s in SCHEMES + BASE:
        e = rep["sets"].get(s)
        if not e:
            continue
        cells = []
        for plat in ("esp32", "pi5"):
            var = e["variant"].get(plat, e["variant"].get("default"))
            for op in ("sign", "verify"):
                r = st.get((s, e["param"], var, plat, op))
                if r and r.get("net_stack_bytes"):
                    cells.append("{:,}".format(int(r["net_stack_bytes"])))
                elif (s, e["param"], var) in nr[plat] or (s == "SDitH" and plat == "esp32"):
                    cells.append(DASH)
                else:
                    cells.append(missing("stack"))
        # code size: .text of the scheme library built for the MicroBlaze
        # (the same portable C as on the ESP32), results/code_microblaze.csv
        mbsize = {r[0]: int(r[1]) for r in csv.reader(open(os.path.join(ROOT, "results", "code_microblaze.csv"))) if len(r) >= 2}
        mvar = e["variant"].get("microblaze", e["variant"].get("default"))
        mrec = next((n for n, v in recipes_all.items() if v["scheme"] == s and v["param"] == e["param"] and v["variant"] == mvar), None)
        if mrec in mbsize:
            cells.append("{:,}".format(mbsize[mrec]))
        elif s == "SDitH":
            cells.append(DASH)
        else:
            cells.append(missing("size"))
        for plat in ("microblaze:vivado", "pi5", "x86:rapl_pkg"):
            pl = plat.split(":")[0]
            var = e["variant"].get(pl, e["variant"].get("default"))
            r = ee.get((s, e["param"], var, plat, "sign"))
            if r:
                v = float(r["E_op_uJ_mean"])
                cells.append("{:,.0f}".format(v) if v >= 100 else "%.1f" % v)
            elif pl == "microblaze" and (s == "SDitH" or (s, e["param"], var) in no_run("microblaze")):
                cells.append(DASH)
            else:
                cells.append(missing("energy"))
        lines.append("%s & %s & %s \\\\" % (s, esc(e["param"]), " & ".join(cells)))
    write("tab_memory_energy.tex", r"""\begin{table}[!htbp]
\caption{Peak stack above an empty run (bytes), code size (bytes, \texttt{.text} of the scheme library built for the MicroBlaze (MB) from the same portable C that runs on the ESP32; the FAEST library holds all four parameter sets) and energy per signing operation ($\mu$J). MicroBlaze$^{\mathrm{a}}$: estimate, total on-chip power from the Vivado power report (0.884~W, vectorless, confidence ``Low'') times the median signing time. Pi~5: measured from the PMIC rails (\texttt{vcgencmd pmic\_read\_adc}, 42 readings per second), mean of ten 15~s windows above the session idle level (3.33~W); it excludes the 5~V input and the PMIC's own conversion loss. 9950X: RAPL package energy, mean of five 10~s windows above the session idle level. The 95\% confidence intervals are in the data archive. Energy on the ESP32 is left to future work.}
\label{tab:memory}
\centering
\scriptsize
\begin{tabular}{llrrrrrrrr}
\toprule
 & & \multicolumn{2}{c}{Stack ESP32} & \multicolumn{2}{c}{Stack Pi 5} & Code & \multicolumn{3}{c}{Energy, signing ($\mu$J)} \\
\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(lr){8-10}
Scheme & Set & S & V & S & V & MB & MicroBlaze$^{\mathrm{a}}$ & Pi 5 & 9950X \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def table4():
    feas = read_csv("results/feasibility.csv")
    fx = {(r["scheme"], r["platform"]): r for r in feas}
    plats = [("esp32", "ESP32"), ("microblaze", "MicroBlaze"), ("pi5", "Pi 5"), ("x86", "9950X"), ("gpu", "GPU")]
    lines = []
    for s in SCHEMES + BASE:
        cells = []
        for p, _ in plats:
            r = fx.get((s, p))
            if r:
                cells.append(esc(r["status"] + ((" (" + r["limit"] + ")") if r.get("limit") else "")))
            elif s == "SDitH" and p in ("esp32", "microblaze"):
                cells.append(r"no build (\texttt{\_\_uint128\_t})")
            else:
                cells.append(missing("feasibility"))
        lines.append("%s & %s \\\\" % (s, " & ".join(cells)))
    write("tab_feasibility.tex", r"""\begin{table}[!htbp]
\caption{Feasibility map. A cell names the limiting resource when a scheme does not run all three operations on a platform.}
\label{tab:feasibility}
\centering
\footnotesize
\begin{tabular}{l""" + "l" * len(plats) + r"""}
\toprule
Scheme & """ + " & ".join(n for _, n in plats) + r""" \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def table7(platform="x86"):
    """One row per tested recipe on the platform: fixed-versus-random |t|, the
    fixed-versus-fixed control, the confirmation run, memcheck, and the
    class of the memcheck sites (results/ct_sites_x86.csv, judged by hand).
    Fresh-copy rows (suffix _fresh), where present, replace the plain ones."""
    rows = read_csv("results/ct_%s.csv" % platform)
    sites = {r["recipe"]: r for r in read_csv("results/ct_sites_%s.csv" % platform)}
    recipes = json.load(open(os.path.join(ROOT, "registry", "recipes.json")))["recipes"]
    by = {}
    for r in rows:
        key = (r["scheme"], r["param"], r["variant"])
        test = r["test"]
        base = test[:-6] if test.endswith("_fresh") else test
        d = by.setdefault(key, {})
        if test.endswith("_fresh") or base not in d:
            d[base] = r
        if test.endswith("_fresh"):
            d["fresh"] = True
    order = SCHEMES + BASE
    keys = sorted(by, key=lambda k: (order.index(k[0]) if k[0] in order else 99, k[2]))
    lines = []
    for k in keys:
        d = by[k]
        f, c, cf, mc = d.get("fixvsrand_sign"), d.get("fixvsfix_control"), d.get("fixvsrand_confirm"), d.get("memcheck_sign")
        tv = lambda r: ("%.1f" % float(r["max_abs_t"])) if r else "--"
        if c and float(c["max_abs_t"]) > 4.5:
            finding = "inconclusive"
        elif f and float(f["max_abs_t"]) > 4.5 and (cf is None or float(cf["max_abs_t"]) > 4.5):
            finding = "leak" if cf else "leak (unconfirmed)"
        elif f and float(f["max_abs_t"]) > 4.5:
            finding = "not repeated"
        elif f:
            finding = "none"
        else:
            finding = missing("ct")
        name = [n for n, v in recipes.items() if (v["scheme"], v["param"], v["variant"]) == k]
        site = sites.get(name[0]) if name else None
        mtxt = "--"
        if mc:
            v = mc["result"]
            mtxt = "0" if v == "no_report" else ("n/a" if v.startswith("not_run") else v.replace("reports_", "").replace("_contexts", ""))
        cls = esc(site["class"]) if site else "--"
        lines.append("%s & %s%s & %s & %s & %s & %s & %s & %s & %s \\\\" % (
            esc(k[0]), esc(k[2]), "$^{\\mathrm{a}}$" if d.get("fresh") else "", f["n"] if f else "--",
            tv(f), tv(c), tv(cf), finding, mtxt, cls))
    if platform == "pi5":
        write("tab_ct_pi5.tex", r"""\begin{table}[!htbp]
\caption{Constant-time tests on signing on the Raspberry Pi 5 (Cortex-A76, three cores in parallel), with the same tests and rules as Table~\ref{tab:ct}. The number of measurements $n$ is set by a one-hour budget per test, so the slow signers get fewer measurements than on the Ryzen. Memcheck: Valgrind 3.22 on AArch64, which decodes the NEON code. $^{\mathrm{a}}$Key copied into a random work slot before every measurement.}
\label{tab:ct_pi5}
\centering
\footnotesize
\begin{tabular}{llrrrrlrl}
\toprule
Scheme & Variant & $n$ & $|t|$ & control & confirm & result & memcheck & class \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")
        return
    write("tab_ct_x86.tex", r"""\begin{table}[!htbp]
\caption{Constant-time tests on signing on the Ryzen 9 9950X. $|t|$: largest Welch statistic of the fixed-versus-random test; control: both classes sign with the same key (false-positive floor); confirm: a second run with fresh data. A result is a leak when $|t|>4.5$ in both runs and the control stays below 4.5, inconclusive when the control exceeds 4.5, and not repeated when only the first run exceeds 4.5. Memcheck: error contexts reported with the secret key marked undefined, capped at 1{,}000 (n/a: Valgrind 3.22 cannot decode GFNI or AVX-512 code); class: our reading of those sites. $^{\mathrm{a}}$Key copied into a random work slot before every measurement.}
\label{tab:ct}
\centering
\footnotesize
\begin{tabular}{llrrrrlrl}
\toprule
Scheme & Variant & $n$ & $|t|$ & control & confirm & result & memcheck & class \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def batch_rates(path, device):
    """{(mode, batch): median verifies/s} from a batch_<recipe>.csv file.
    CPU: verifies/s of the BATCH rows. GPU: end to end, i.e. the median
    kernel time plus the host-to-device and device-to-host copies of the
    GPU_XFER row. Repetitions with all_ok=0 are dropped; a batch without a
    clean repetition has no rate."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return {}
    ns, xfer = {}, {}
    for r in csv.reader(open(full)):
        if not r:
            continue
        if r[0] == "BATCH" and r[5] == device and r[-1] == "1":
            ns.setdefault((r[6], int(r[8])), []).append(float(r[10]))
        elif r[0] == "GPU_XFER":
            xfer[(r[4], int(r[5]))] = float(r[6]) + float(r[7])
    out = {}
    for k, v in ns.items():
        v = sorted(v)
        med = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
        t = med + (xfer.get(k, 0.0) if device == "gpu" else 0.0)
        out[k] = k[1] / (t / 1e9)
    return out


def rate_fmt(x):
    if x >= 1e6:
        return "%.2fM" % (x / 1e6)
    if x >= 1e4:
        return "%.0fk" % (x / 1e3)
    if x >= 1e3:
        return "%.1fk" % (x / 1e3)
    return "%.0f" % x if x >= 10 else "%.1f" % x


def table8():
    rep = representative()
    recipes = json.load(open(os.path.join(ROOT, "registry", "recipes.json")))["recipes"]
    batches = [1, 64, 1024, 16384, 65536]
    lines = []
    for s in SCHEMES + BASE:
        e = rep["sets"].get(s)
        if not e:
            continue
        var = e["variant"].get("x86", e["variant"].get("default"))
        cpu_rec = next((n for n, v in recipes.items() if v["scheme"] == s and v["param"] == e["param"] and v["variant"] == var), None)
        gpu_rec = e.get("recipe_gpu")
        cpu = batch_rates("results/raw/x86/batch_%s.csv" % cpu_rec, "cpu") if cpu_rec else {}
        gpu = batch_rates("results/raw/gpu/batch_%s.csv" % gpu_rec, "gpu") if gpu_rec else {}
        cells = [rate_fmt(cpu[("shared", b)]) if ("shared", b) in cpu else missing("batch") for b in batches]
        gpath = os.path.join(ROOT, "results", "raw", "gpu", "batch_%s.csv" % gpu_rec) if gpu_rec else ""
        gtext = open(gpath).read() if gpath and os.path.exists(gpath) else ""
        gdone = "GPU_DONE" in gtext
        skipped = {int(l.split(",")[6]) for l in gtext.splitlines() if l.startswith("SKIP,time_budget") and ",shared," in l}
        def gcell(b):
            if ("shared", b) in gpu:
                return rate_fmt(gpu[("shared", b)])
            if b in skipped:
                return "t/o"
            return DASH if gdone else missing("gpu")
        if not gpu_rec:
            cells += [DASH] * 5
        else:
            cells += [gcell(b) for b in batches]
        cross = next((b for b in batches if ("shared", b) in cpu and ("shared", b) in gpu
                      and gpu[("shared", b)] > cpu[("shared", b)]), None)
        if cpu and gpu:
            cells.append("{:,}".format(cross) if cross else "none")
        else:
            cells.append(DASH if (not gpu_rec or gdone) else missing("crossover"))
        lines.append("%s & %s \\\\" % (s, " & ".join(cells)))
    write("tab_batch.tex", r"""\begin{table}[!htbp]
\caption{Verifications per second, shared-key mode, at batch sizes 1, 64, 1{,}024, 16{,}384 and 65{,}536 on the 9950X with 32 threads (recipe of Table~\ref{tab:cycles}) and on the RTX~5070~Ti (portable recipe, one thread per signature, end to end including copies), and the smallest batch at which the GPU is faster. A dash marks a scheme or batch without a correct GPU result (Table~\ref{tab:feasibility} gives the reason); t/o marks a batch size skipped because one run would exceed 40 minutes. SNOVA on the GPU uses the AES version of SNOVA\_I\_K, because the SHAKE versions reject every valid signature there.}
\label{tab:batch}
\centering
\scriptsize
\setlength{\tabcolsep}{3pt}
\begin{tabular}{l rrrrr rrrrr r}
\toprule
 & \multicolumn{5}{c}{9950X, 32 threads} & \multicolumn{5}{c}{RTX 5070 Ti} & \\
\cmidrule(lr){2-6}\cmidrule(lr){7-11}
Scheme & 1 & 64 & 1k & 16k & 64k & 1 & 64 & 1k & 16k & 64k & Cross. \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def table9():
    rows = read_csv("paper/data/message_cost.csv")
    rep = representative()
    by = {(r["scheme"], r["param"]): r for r in rows}
    lines = []
    for s in SCHEMES + BASE:
        e = rep["sets"].get(s)
        r = by.get((s, e["param"])) if e else None
        if not r:
            lines.append("%s & %s \\\\" % (s, " & ".join([missing("message_cost.py")] * 5)))
            continue
        lines.append("%s & %s & %s & %s & %s & %s \\\\" % (
            s, esc(r["param"]), r["frames_154"], r["frames_ble"], r["frames_ipv6"],
            "{:,}".format(int(r["chain_bytes"])) + ("" if r["chain_method"] == "modelled" else "$^{\\mathrm{a}}$")))
    write("tab_message.tex", r"""\begin{table}[!t]
\caption{Frames needed for one signed 64-byte reading and bytes of a three-certificate chain. 802.15.4: 127-byte frames, 9-byte MAC header and 2-byte FCS, 6LoWPAN with uncompressed IPv6 and UDP headers and RFC~4944 fragmentation~\cite{ieee802154,rfc4944}. BLE: 251-byte LL payload with an L2CAP credit-based channel~\cite{btcore}. IPv6: 1{,}280-byte MTU with IPv6 fragmentation~\cite{rfc8200}. Chain bytes: X.509 structure measured from an OpenSSL Ed25519 chain, key and signature replaced, NIST-arc OIDs; $^{\mathrm{a}}$ marks chains measured directly.}
\label{tab:message}
\centering
\footnotesize
\setlength{\tabcolsep}{4pt}
\begin{tabular}{llrrrr}
\toprule
Scheme & Set & 802.15.4 & BLE & IPv6 & Chain (B) \\
\midrule
""" + "\n".join(lines) + r"""
\bottomrule
\end{tabular}
\end{table}
""")


def main():
    table1()
    table9()
    table4()
    table5()
    table6()
    table7()
    table7("pi5")
    table8()
    print("tables written to", OUT)


if __name__ == "__main__":
    main()
