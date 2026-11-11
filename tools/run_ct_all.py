#!/usr/bin/env python3
"""run_ct_all.py - constant-time tests (the timing-leakage table) for the representative
Category 1 sets, several recipes at a time on separate physical cores.

  python3 tools/run_ct_all.py --platform x86 --cores 2-13
  python3 tools/run_ct_all.py --platform x86 --recipe uov-Ip_pkc-opt-gfni --cores 2

Recipes: for each scheme in paper/data/representative_sets.json, the
platform's variant (the timed one in the cycle and energy tables) and the default
reference variant; duplicates are dropped.

Each recipe runs ct/run_ct.sh (fixed-versus-random t-test, then Valgrind
memcheck) pinned to one core with taskset. The number of measurements is
--max-n (default 1,000,000), reduced for slow signers so that one test
takes about --budget-h hours, but never below --min-n. The signing time
comes from the recipe's speed run (results/raw/<platform>/<recipe>.csv).
Every CT row records its n, so the paper can state it.

The fixed-versus-random test interleaves both classes at random, so a
steady load on other cores shifts both classes alike; still, run nothing
else on the machine. On the 9950X logical CPUs 0-15 are the first threads
of the 16 cores and 16-31 their SMT siblings: give cores from 0-15 only
and leave the siblings idle.
"""
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run_bench import kat_ok  # noqa: E402


def cores_arg(s):
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def representative(platform, recipes):
    sets = json.load(open(os.path.join(TOP, "paper", "data", "representative_sets.json")))["sets"]
    names = []
    for scheme, s in sets.items():
        prefix = [k for k, v in recipes.items() if v["scheme"].replace("-", "").lower() == scheme.replace("-", "").lower()
                  and v["param"] == s["param"]]
        if not prefix:
            # Parameter names differ between the registry and the paper for
            # some baselines (ML-DSA-44 vs 44); match on scheme and variant.
            prefix = [k for k, v in recipes.items() if v["scheme"].replace("-", "").lower() == scheme.replace("-", "").lower()]
        timed = s["variant"].get(platform, s["variant"]["default"])
        wanted = [timed, s["variant"]["default"]]
        # Valgrind 3.22 cannot decode GFNI or AVX-512 code, so memcheck cannot
        # check those variants; the AVX2 sibling is added for that test.
        if timed in ("opt-gfni", "opt-avx512"):
            wanted.append("opt-avx2")
        for var in wanted:
            for k in sorted(prefix):
                if recipes[k]["variant"] == var and k not in names:
                    names.append(k)
                    break
    return names


def sign_ns(platform, recipe):
    path = os.path.join(TOP, "results", "raw", platform, recipe + ".csv")
    if not os.path.exists(path):
        return None
    v = [int(r[9]) for r in csv.reader(open(path)) if len(r) > 9 and r[0] == "SPEED" and r[6] == "sign"]
    return statistics.median(v) if v else None


def ensure_built(platform, names, memh):
    """Rebuild, before any timing starts, every recipe whose test programs
    are missing or older than their sources or tools/hbuild.py. Doing this
    up front keeps two jobs of one recipe from rebuilding it at the same
    time (one job then finds no binary)."""
    srcs = [os.path.join(TOP, "ct", "fixvsrand_sign.c"), os.path.join(TOP, "ct", "memcheck_sign.c"),
            os.path.join(HERE, "hbuild.py")]
    newest = max(os.path.getmtime(x) for x in srcs)
    stale = []
    for n in sorted(set(names)):
        b = os.path.join(TOP, "build", platform, n)
        progs = [os.path.join(b, "ct_fixvsrand")] + ([os.path.join(b, "ct_memcheck")] if memh else [])
        if any(not os.path.exists(x) or os.path.getmtime(x) < newest for x in progs):
            stale.append(n)

    def build(n):
        r = subprocess.run([sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n,
                            "--platform", platform], capture_output=True)
        ok = os.path.exists(os.path.join(TOP, "build", platform, n, "ct_fixvsrand"))
        print("built %-36s %s" % (n, "ok" if ok else "FAILED (rc=%d)" % r.returncode), flush=True)

    if stale:
        print("rebuilding %d recipes before timing" % len(stale), flush=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(build, stale))


def run_direct(platform, n, N, seed, env, core, out):
    """One ct_fixvsrand run outside run_ct.sh (control and confirmation)."""
    exe = os.path.join(TOP, "build", platform, n, "ct_fixvsrand")
    r = subprocess.run(["taskset", "-c", str(core), exe, str(N), "64", seed],
                       env=dict(os.environ, **env), capture_output=True, text=True)
    row = [l for l in r.stdout.splitlines() if l.startswith("CT,")]
    if row:
        with open(out, "a") as f:
            f.write(row[0] + "\n")
    return row[0] if row else "no CT row, rc=%d" % r.returncode


def fresh(a):
    """Fresh-copy runs for recipes whose version-3 control failed (UOV)."""
    if not a.recipe:
        sys.exit("--fresh needs --recipe")
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    out = os.path.join(TOP, "results", "ct_%s.csv" % a.platform)
    have = set()
    if os.path.exists(out):
        for r in csv.reader(open(out)):
            if len(r) > 6 and r[0] == "CT":
                have.add((r[1], r[2], r[3], r[5]))
    jobs = []
    for n in a.recipe:
        rec = recipes[n]
        t = sign_ns(a.platform, n)
        N = int(min(a.max_n, max(a.min_n, a.budget_h * 3600e9 / t))) if t else a.max_n
        for test, env, seed in (("fixvsrand_sign_fresh", {}, "92"), ("fixvsrand_confirm_fresh", {}, "167"),
                                ("fixvsfix_control_fresh", {"CT_CONTROL": "1"}, "92")):
            if (rec["scheme"], rec["param"], rec["variant"], test) in have:
                print("skip %-36s %s already in %s" % (n, test, os.path.basename(out)))
                continue
            jobs.append((n, N, test, dict(env, CT_FRESHCOPY="1"), seed))
    for j in jobs:
        print("plan %-36s %-24s n=%d" % (j[0], j[2], j[1]))
    if a.list:
        return
    ensure_built(a.platform, a.recipe, os.path.exists("/usr/include/valgrind/memcheck.h"))
    cores = cores_arg(a.cores)
    free = list(cores)

    def job(j):
        n, N, test, env, seed = j
        core = free.pop(0)
        try:
            t0 = time.time()
            row = run_direct(a.platform, n, N, seed, env, core, out)
            print("done %-36s core %2d  %.1f h  %s" % (n, core, (time.time() - t0) / 3600, row), flush=True)
        finally:
            free.append(core)

    with ThreadPoolExecutor(max_workers=len(cores)) as ex:
        list(ex.map(job, jobs))


def followup(a):
    """Second look at every flagged recipe. A real key dependence shows up
    again with fresh data (fixvsrand_confirm) and vanishes when both classes
    use the same key (fixvsfix_control). A control above 4.5 means the
    set-up, not the key, produces the difference."""
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    out = os.path.join(TOP, "results", "ct_%s.csv" % a.platform)
    rows = [r for r in csv.reader(open(out)) if len(r) > 8 and r[0] == "CT"]
    have = {(r[1], r[2], r[3], r[5]) for r in rows}
    jobs = []
    for r in rows:
        if r[5] != "fixvsrand_sign" or r[8] != "leak":
            continue
        name = [k for k, v in recipes.items() if (v["scheme"], v["param"], v["variant"]) == (r[1], r[2], r[3])]
        if not name:
            continue
        for test, env, seed in (("fixvsrand_confirm", {}, "167"), ("fixvsfix_control", {"CT_CONTROL": "1"}, "92")):
            if (r[1], r[2], r[3], test) in have:
                print("skip %-36s %s already in %s" % (name[0], test, os.path.basename(out)))
                continue
            jobs.append((name[0], int(r[6]), test, env, seed))
    for j in jobs:
        print("plan %-36s %-18s n=%d" % (j[0], j[2], j[1]))
    if a.list or not jobs:
        return
    ensure_built(a.platform, [j[0] for j in jobs], os.path.exists("/usr/include/valgrind/memcheck.h"))
    cores = cores_arg(a.cores)
    free = list(cores)

    def job(j):
        n, N, test, env, seed = j
        core = free.pop(0)
        try:
            t0 = time.time()
            row = run_direct(a.platform, n, N, seed, env, core, out)
            print("done %-36s core %2d  %.1f h  %s" % (n, core, (time.time() - t0) / 3600, row), flush=True)
        finally:
            free.append(core)

    with ThreadPoolExecutor(max_workers=len(cores)) as ex:
        list(ex.map(job, jobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="x86", choices=["x86", "pi5"])
    ap.add_argument("--recipe", action="append", default=[])
    ap.add_argument("--cores", default="2-13")
    ap.add_argument("--max-n", type=int, default=1000000)
    ap.add_argument("--min-n", type=int, default=20000)
    ap.add_argument("--budget-h", type=float, default=3.0)
    ap.add_argument("--list", action="store_true", help="print the plan and stop")
    ap.add_argument("--control", action="store_true",
                    help="also run the fixed-versus-fixed control for every recipe (same n)")
    ap.add_argument("--fresh", action="store_true",
                    help="with --recipe: fixed-versus-random, confirmation and control runs with CT_FRESHCOPY=1 "
                         "(key copied into a random work slot before every measurement)")
    ap.add_argument("--followup", action="store_true",
                    help="for every recipe whose fixvsrand_sign row says leak: a confirmation run with a "
                         "fresh seed and a fixed-versus-fixed control run, same n, on separate cores")
    a = ap.parse_args()
    if a.followup:
        return followup(a)
    if a.fresh:
        return fresh(a)

    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    names = a.recipe or representative(a.platform, recipes)
    ok = kat_ok(a.platform)
    out = os.path.join(TOP, "results", "ct_%s.csv" % a.platform)
    done = set()
    done_ctl = set()
    if os.path.exists(out):
        for r in csv.reader(open(out)):
            if len(r) > 6 and r[0] == "CT" and r[5] == "fixvsrand_sign":
                done.add((r[1], r[2], r[3]))
            if len(r) > 6 and r[0] == "CT" and r[5] == "fixvsfix_control":
                done_ctl.add((r[1], r[2], r[3]))
    else:
        with open(out, "w") as f:
            f.write("tag,scheme,param,variant,platform,test,n,max_abs_t,result\n")

    plan = []
    for n in names:
        rec = recipes[n]
        if n not in ok:
            print("skip %-36s no passing KAT row on %s" % (n, a.platform))
            continue
        key = (rec["scheme"], rec["param"], rec["variant"])
        if key in done and (not a.control or key in done_ctl):
            print("skip %-36s already in %s" % (n, os.path.basename(out)))
            continue
        t = sign_ns(a.platform, n)
        if t is None:
            print("skip %-36s no speed run to size the test" % n)
            continue
        # Time per measurement is about one signature; the warm-up and the
        # key pool add little.
        N = int(min(a.max_n, max(a.min_n, a.budget_h * 3600e9 / t)))
        if key not in done:
            plan.append((n, N, N * t / 3600e9, "main"))
        if a.control and key not in done_ctl:
            plan.append((n, N, N * t / 3600e9, "control"))
    plan.sort(key=lambda p: -p[2])      # longest first, so the cores stay busy
    for n, N, h, kind in plan:
        print("plan %-36s %-7s n=%8d  about %.1f h" % (n, kind, N, h))
    if a.list or not plan:
        return

    memh = os.path.exists("/usr/include/valgrind/memcheck.h")
    if not memh:
        print("note: valgrind is not installed (sudo apt install valgrind); memcheck will be skipped")
    cores = cores_arg(a.cores)
    free = list(cores)
    logdir = os.path.join(TOP, "results", "ct_logs")
    os.makedirs(logdir, exist_ok=True)

    ensure_built(a.platform, [p[0] for p in plan], memh)

    def job(item):
        n, N, _, kind = item
        core = free.pop(0)
        try:
            t0 = time.time()
            if kind == "control":
                row = run_direct(a.platform, n, N, "92", {"CT_CONTROL": "1"}, core, out)
                print("done %-36s core %2d  %.1f h  %s" % (n, core, (time.time() - t0) / 3600, row), flush=True)
                return
            with open(os.path.join(logdir, n + ".log"), "w") as lg:
                r = subprocess.run(["taskset", "-c", str(core), "sh", os.path.join(TOP, "ct", "run_ct.sh"),
                                    n, a.platform, str(N)], stdout=lg, stderr=subprocess.STDOUT)
            rows = [l for l in open(os.path.join(logdir, n + ".log")).read().splitlines() if l.startswith("CT,")]
            print("done %-36s core %2d  %.1f h  rc=%d  %s" % (n, core, (time.time() - t0) / 3600, r.returncode,
                                                             " | ".join(rows)), flush=True)
        finally:
            free.append(core)

    with ThreadPoolExecutor(max_workers=len(cores)) as ex:
        list(ex.map(job, plan))
    print("results in", out)


if __name__ == "__main__":
    main()
