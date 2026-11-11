#!/usr/bin/env python3
"""run_batch.py - CPU batch verification sweep on the Ryzen 9 9950X (RQ4).

  tools/run_batch.py --platform x86 --category 1
  tools/run_batch.py --platform x86 --match uov-Ip --threads 32

For every recipe with a passing KAT row on the platform, runs
  cpu_batch_verify MODE BATCH REPS THREADS
for MODE in shared and distinct and BATCH in 1, 64, 1024, 16384, 65536,
and writes the BATCH lines to results/raw/<platform>/batch_<recipe>.csv.

A batch that cannot be allocated in host memory prints an ERROR line,
which stays in the file: the largest batch that ran is a result.
The thread count defaults to every hardware thread (os.cpu_count()).
Set the CPU boost and governor state before the run (see README.md).
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from kat_all import category  # noqa: E402
from run_bench import kat_ok  # noqa: E402

BATCHES = [1, 64, 1024, 16384, 65536]


def finished(path, last_batch):
    """A batch file is complete when it ends with BATCH_DONE, or (files from
    before that marker) when it holds a row for the last distinct-key batch."""
    if not os.path.exists(path):
        return False
    for line in open(path):
        p = line.strip().split(",")
        if p[0] == "BATCH_DONE":
            return True
        if p[0] == "BATCH" and len(p) > 8 and p[6] == "distinct" and p[8] == str(last_batch):
            return True
        if p[0] == "ERROR" and "distinct" in p and str(last_batch) in p:
            return True
    return False


def rebuild_batch(platform, names, jobs):
    """Rebuilds (in parallel) every recipe whose cpu_batch_verify is older
    than the threaded setup (no batch_tls.ok in its build folder). The old
    program signs the 65,536-signature inputs on one core, which takes
    hours for the slow signers; the new one signs them on every thread."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [n for n in names if not os.path.exists(os.path.join(TOP, "build", platform, n, "batch_tls.ok"))]
    if not todo:
        return
    print("rebuilding %d recipes for the threaded batch setup (%d at a time)" % (len(todo), jobs), flush=True)

    def one(n):
        r = subprocess.run([sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n, "--platform", platform],
                           capture_output=True, text=True)
        ok = os.path.exists(os.path.join(TOP, "build", platform, n, "batch_tls.ok"))
        print("built %-40s %s" % (n, "ok" if ok else "FAILED rc=%d %s" % (r.returncode, (r.stdout + r.stderr).strip()[-200:])),
              flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        list(ex.map(one, todo))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="x86", choices=["x86", "x86-generic", "pi5"])
    ap.add_argument("--category")
    ap.add_argument("--match", default="")
    ap.add_argument("--recipe", action="append", default=[], help="exact recipe name (repeatable)")
    ap.add_argument("--omp-active", action="store_true",
                    help="OpenMP threads spin between batches and stay on their CPUs "
                         "(OMP_WAIT_POLICY=active, OMP_PROC_BIND=close, OMP_PLACES=threads)")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    ap.add_argument("--batches", default=",".join(str(b) for b in BATCHES))
    ap.add_argument("--timeout", type=int, default=7200, help="seconds per batch size")
    ap.add_argument("--force", action="store_true", help="redo recipes that are already finished")
    ap.add_argument("--jobs", type=int, default=8, help="parallel rebuilds of cpu_batch_verify")
    a = ap.parse_args()
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    names = [n for n in sorted(recipes) if a.match in n and (not a.recipe or n in a.recipe)
             and a.platform in recipes[n].get("platforms", [a.platform])]
    if a.category:
        names = [n for n in names if category(recipes[n]) == a.category]
    okset = kat_ok(a.platform)
    raw = os.path.join(TOP, "results", "raw", a.platform)
    os.makedirs(raw, exist_ok=True)
    if a.omp_active:
        os.environ.update(OMP_WAIT_POLICY="active", OMP_PROC_BIND="close", OMP_PLACES="threads")
    rebuild_batch(a.platform, [n for n in names if n in okset], a.jobs)
    for n in names:
        exe = os.path.join(TOP, "build", a.platform, n, "cpu_batch_verify")
        if n not in okset or not os.path.exists(exe):
            print("skip %-40s (no passing KAT or no cpu_batch_verify)" % n)
            continue
        out = os.path.join(raw, "batch_%s.csv" % n)
        sizes = [int(x) for x in a.batches.split(",")]
        if not a.force and finished(out, sizes[-1]):
            print("skip %-40s already measured (use --force to redo)" % n)
            continue
        # Written to a .part file first: a power cut never leaves a half
        # file that looks finished.
        part = out + ".part"
        with open(part, "w") as f:
            for mode in ("shared", "distinct"):
                for b in [int(x) for x in a.batches.split(",")]:
                    t0 = time.time()
                    try:
                        r = subprocess.run([exe, mode, str(b), str(a.reps), str(a.threads)],
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           timeout=a.timeout)
                        if r.returncode < 0:
                            # A crash during the threaded setup (a package that is not
                            # thread-safe, e.g. SQIsign ref-portable) is retried once
                            # with the setup on one thread.
                            f.write("NOTE,crash_%d_in_threaded_setup,%s,%d,retry_on_one_thread\n" % (-r.returncode, mode, b))
                            r = subprocess.run([exe, mode, str(b), str(a.reps), str(a.threads)],
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                               timeout=a.timeout, env=dict(os.environ, BATCH_SETUP_THREADS="1"))
                        f.write(r.stdout)
                        if r.returncode != 0:
                            f.write("ERROR,exit_code,%d,%s,%d\n" % (r.returncode, mode, b))
                    except subprocess.TimeoutExpired:
                        f.write("ERROR,timeout,%s,%d,%d\n" % (mode, b, a.timeout))
                    f.flush()
                    print("%-40s %-8s %6d  %7.1f s" % (n, mode, b, time.time() - t0), flush=True)
            f.write("BATCH_DONE,%s\n" % n)
        os.replace(part, out)


if __name__ == "__main__":
    main()
