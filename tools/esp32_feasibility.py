#!/usr/bin/env python3
"""esp32_feasibility.py - classify every ESP32 recipe and fill the feasibility table.

  python3 tools/esp32_feasibility.py

Reads results/raw/esp32/<recipe>.csv (with .csv.log) and results/kat_esp32.csv.
Writes
  results/feasibility_sets_esp32.csv  one row per recipe: status, limit, detail
  results/feasibility.csv             one row per scheme and platform (the feasibility table);
                                      rows of other platforms are kept

Rules (the evidence for each is in the raw CSV):
  runs        KAT matches the x86-64 reference and every timed run has ok=1
  keygen only key generation runs and matches the KAT; signing fails
  no run      the board crashes or every operation fails
Limit
  stack       the harness asked for more task stack than the largest internal
              RAM block (NOTE,task_stack_reduced) and the board then crashed;
              the need is (wanted - 16 KiB) / 1.25, the 32-bit x86 peak
  heap        a buffer allocation failed (ERROR,alloc_failed), or an operation
              returned an error (ok=0) or crashed on a store with no stack note
"""
import csv
import glob
import json
import os

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(TOP, "results", "raw", "esp32")


def classify(path, kat_status):
    rows = [r for r in csv.reader(open(path, errors="replace")) if r]
    ok = {}
    for r in rows:
        if r[0] == "SPEED":
            ok.setdefault(r[6], set()).add(r[-1])
    note = next((r for r in rows if r[0] == "NOTE" and r[1] == "task_stack_reduced"), None)
    err = next((r for r in rows if r[0] == "ERROR"), None)
    good = [op for op in ("keypair", "sign", "verify") if ok.get(op) == {"1"}]
    n_verify = sum(1 for r in rows if r[0] == "SPEED" and r[6] == "verify")
    if kat_status == "PASS" and len(good) == 3:
        detail = ""
        reduced = [r for r in rows if r[0] == "NOTE" and "runs_reduced_to" in r]
        if reduced:
            detail = "; ".join("%s %s runs" % (r[5], r[-1]) for r in reduced)
        if n_verify not in (0, 100, 1000):
            detail = (detail + "; " if detail else "") + "verify %d runs (8 h capture limit)" % n_verify
        return "runs", "", detail
    status = "keygen only" if good == ["keypair"] else "no run"
    if note and err and err[1] == "crash":
        need = (int(note[3]) - 16384) / 1.25 / 1024
        got = int(note[5]) / 1024
        return status, "stack", "needs about %.0f KB of stack, %.0f KB available" % (need, got)
    if err and err[1] != "crash":
        return status, "heap", ",".join(err[5:])[:120]
    if err:
        log = path + ".log"
        text = open(log, errors="replace").read() if os.path.exists(log) else ""
        if "EXCVADDR: 0x00000000" in text:
            # Store to address 0 inside memcpy/memset: an allocation returned
            # NULL and the package's assert() is compiled out (NDEBUG).
            return status, "heap", "store to address 0: an unchecked allocation returned NULL"
        return status, "heap", "crash with no stack shortage (inferred): " + err[2][:80]
    return status, "heap", "operations return an error (ok=0): " + \
        ", ".join(op for op in ("keypair", "sign", "verify") if op not in good)


def main():
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    kat = {r["recipe"]: r["status"] for r in csv.DictReader(open(os.path.join(TOP, "results", "kat_esp32.csv")))}
    sets = []
    for f in sorted(glob.glob(os.path.join(RAW, "*.csv"))):
        name = os.path.basename(f)[:-4]
        rec = recipes.get(name, {})
        st, lim, det = classify(f, kat.get(name, "FAIL"))
        sets.append({"recipe": name, "scheme": rec.get("scheme", "?"), "param": rec.get("param", "?"),
                     "variant": rec.get("variant", "?"), "status": st, "limit": lim, "detail": det})
    out = os.path.join(TOP, "results", "feasibility_sets_esp32.csv")
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sets[0]))
        w.writeheader()
        w.writerows(sets)

    # One cell per scheme for the feasibility table.
    per = {}
    for s in sets:
        per.setdefault(s["scheme"], []).append(s)
    cells = []
    for scheme, ss in per.items():
        n = len(ss)
        k = sum(1 for s in ss if s["status"] == "runs")
        lims = sorted({s["limit"] for s in ss if s["limit"]})
        if k == n:
            status, limit = "runs", ""
        elif k == 0:
            kg = sum(1 for s in ss if s["status"] == "keygen only")
            status = ("key generation only, %d of %d builds" % (kg, n)) if kg else "no run"
            limit = "/".join(lims)
        else:
            status, limit = "%d of %d builds" % (k, n), "/".join(lims)
        cells.append({"scheme": scheme, "platform": "esp32", "status": status, "limit": limit})
    # Schemes with no ESP32 build (SDitH) are written by make_tables.py itself.

    fp = os.path.join(TOP, "results", "feasibility.csv")
    keep = []
    if os.path.exists(fp):
        keep = [r for r in csv.DictReader(open(fp)) if r["platform"] != "esp32"]
    with open(fp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["scheme", "platform", "status", "limit"])
        w.writeheader()
        w.writerows(keep + cells)
    for c in cells:
        print("%-8s %-40s %s" % (c["scheme"], c["status"], c["limit"]))
    print("wrote", os.path.relpath(out, TOP), "and results/feasibility.csv")


if __name__ == "__main__":
    main()
