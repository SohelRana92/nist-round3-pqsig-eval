#!/usr/bin/env python3
"""gpu_feasibility.py - classify every GPU recipe and fill the GPU column of the feasibility table.

  python3 tools/gpu_feasibility.py

Reads results/gpu_build_summary.json (gpu/build_gpu.py) and
results/raw/gpu/batch_<recipe>.csv (tools/run_gpu.py). Writes
  results/feasibility_sets_gpu.csv   one row per recipe: status, limit, detail
  results/feasibility.csv            GPU rows of the feasibility table; other rows kept

Status of a recipe
  runs        at least one batch verified with every result correct (all_ok=1)
  no build    the portable C does not compile for the GPU; the reason is
              read from the compiler logs (variable-length arrays, missing
              functions)
  no run      built, but no batch ran: the per-thread stack cannot be
              reserved for every resident thread (limit "stack"), a thread
              faulted (limit "kernel fault") or results were wrong
Mutable global variables (state shared by all threads) are listed in the
detail; a recipe whose results are all correct despite them is "runs".
"""
import csv
import glob
import json
import os

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_reason(b):
    logs = [m.get("log") for m in b.get("missing_bitcode", []) + b.get("missing_bitcode_unused", []) if m.get("log")]
    text = ""
    for l in logs:
        if l and os.path.exists(l):
            text += open(l, errors="replace").read()
    n_vla = text.count("variable length arrays are not supported")
    if n_vla:
        return "VLA", "%d variable-length arrays; PTX has no dynamic stack allocation" % n_vla
    if b.get("unresolved"):
        return "unresolved", "functions not available on the GPU: " + ", ".join(b["unresolved"][:5])
    return b.get("status", "?"), b.get("detail", "")[:120]


def classify(name, b):
    if b.get("status") != "ok":
        lim, det = build_reason(b)
        return "no build", lim, det
    path = os.path.join(TOP, "results", "raw", "gpu", "batch_%s.csv" % name)
    if not os.path.exists(path):
        return "built", "", "stack %d B per thread, %s registers (not run yet)" % (b.get("stack_bound", 0), b.get("registers"))
    rows = [r for r in csv.reader(open(path)) if r]
    # A batch of 1 holds only the deliberately flipped signature, so it
    # shows that a forgery is rejected but not that a valid signature is
    # accepted: it does not count as a run on its own.
    good = [r for r in rows if r[0] == "BATCH" and r[-1] == "1" and int(r[8]) > 1]
    bad = [r for r in rows if r[0] == "BATCH" and r[-1] != "1"]
    errs = [r for r in rows if r[0] == "ERROR"]
    mut = ";".join(b.get("mutable_globals", []))
    if good:
        largest = max(int(r[8]) for r in good)
        det = "largest batch %d" % largest
        if mut:
            det += "; shared globals: " + mut
        return "runs", "", det
    if errs:
        what = errs[0][1]
        if what in ("stack_limit", "heap_limit"):
            return "no run", "stack", "needs %d KB per thread for every resident thread" % (b.get("stack_bound", 0) // 1024)
        if what == "kernel":
            return "no run", "kernel fault", errs[0][2]
        return "no run", what, errs[0][2] if len(errs[0]) > 2 else ""
    if bad:
        return "no run", "wrong results", ("shared globals: " + mut) if mut else "valid signatures rejected on the GPU"
    return "no run", "?", ""


def main():
    sp = os.path.join(TOP, "results", "gpu_build_summary.json")
    if not os.path.exists(sp):
        raise SystemExit("run gpu/build_gpu.py first")
    builds = {r["recipe"]: r for r in json.load(open(sp))}
    sets = []
    for n in sorted(builds):
        b = builds[n]
        st, lim, det = classify(n, b)
        sets.append({"recipe": n, "scheme": b["scheme"], "param": b["param"], "variant": b["variant"],
                     "status": st, "limit": lim, "detail": det})
    out = os.path.join(TOP, "results", "feasibility_sets_gpu.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sets[0]))
        w.writeheader()
        w.writerows(sets)
    per = {}
    for s in sets:
        per.setdefault(s["scheme"], []).append(s)
    cells = []
    for scheme, ss in per.items():
        if any(s["status"] == "built" for s in ss):
            continue        # not measured yet: the feasibility table keeps its to-do mark
        n = len(ss)
        k = sum(1 for s in ss if s["status"] == "runs")
        lims = "/".join(sorted({s["limit"] for s in ss if s["limit"]}))
        if k == n:
            status, limit = "runs", ""
        elif k == 0:
            nb = all(s["status"] == "no build" for s in ss)
            status, limit = ("no build" if nb else "no run"), lims
        else:
            status, limit = "%d of %d builds" % (k, n), lims
        cells.append({"scheme": scheme, "platform": "gpu", "status": status, "limit": limit})
    fp = os.path.join(TOP, "results", "feasibility.csv")
    keep = [r for r in csv.DictReader(open(fp)) if r["platform"] != "gpu"] if os.path.exists(fp) else []
    with open(fp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["scheme", "platform", "status", "limit"])
        w.writeheader()
        w.writerows(keep + cells)
    for s in sets:
        print("%-38s %-9s %-14s %s" % (s["recipe"], s["status"], s["limit"], s["detail"][:70]))
    print("wrote", os.path.relpath(out, TOP), "and results/feasibility.csv")


if __name__ == "__main__":
    main()
