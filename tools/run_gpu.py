#!/usr/bin/env python3
"""run_gpu.py - GPU batch verification sweep on the RTX 5070 Ti (RQ4).

  python3 tools/run_gpu.py --category 1
  python3 tools/run_gpu.py --recipe uov-Ip_pkc-ref-portable --batches 1024 --reps 1   # quick check

For every recipe with a GPU kernel from gpu/build_gpu.py (status ok) and a
passing KAT row on the CPU platform (default x86):
  1. cpu_batch_verify writes the batch file (keys, signed messages,
     expected results, messages) with BATCH_DUMP; the same inputs the
     CPU sweep verifies;
  2. gpu_batch_verify verifies the batch on the GPU, checks every result
     against the expected one and times the kernel (REPS repetitions after
     one warm-up);
  3. the batch file is deleted.
for MODE in shared and distinct and BATCH in 1, 64, 1024, 16384, 65536.
Rows go to results/raw/gpu/batch_<recipe>.csv; a finished recipe ends with
GPU_DONE and is skipped next time unless --force.

Failures are results, not crashes of the sweep:
  ERROR,stack_limit   the per-thread stack cannot be reserved for every
                      resident thread (16 GB is not enough)
  ERROR,gpu_alloc_*   the batch does not fit in GPU memory; larger batches
                      of that mode are skipped
  ERROR,kernel        a thread trapped, read out of range, or the display
                      watchdog stopped the kernel; the batch is first retried
                      with 16384, 2048 and 256 signatures per launch (RETRY
                      rows), since a full device heap shows up the same way
  SKIP,dump_too_large the batch file would exceed --max-dump-gb

Before timing: lock the GPU clocks (see README.md),
close the desktop if possible (the display watchdog and the compositor
share the GPU), and run nothing else on the machine.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from kat_all import category  # noqa: E402
from run_bench import kat_ok  # noqa: E402

BATCHES = [1, 64, 1024, 16384, 65536]
MLEN = 32


def cuda_home():
    for c in (os.environ.get("CUDA_HOME"), "/usr/local/cuda"):
        if c and os.path.exists(os.path.join(c, "include", "cuda.h")):
            return c
    nv = shutil.which("nvcc")
    if nv:
        return os.path.dirname(os.path.dirname(os.path.realpath(nv)))
    sys.exit("cuda.h not found: set CUDA_HOME")


def host_program():
    exe = os.path.join(TOP, "gpu", "gpu_batch_verify")
    src = exe + ".c"
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        ch = cuda_home()
        # The stub library is only for linking; at run time the program
        # loads the driver's libcuda.so.1.
        r = subprocess.run(["gcc", "-O2", "-o", exe, src, "-I" + os.path.join(ch, "include"),
                            "-L" + os.path.join(ch, "lib64", "stubs"), "-L" + os.path.join(ch, "lib64"), "-lcuda"])
        if r.returncode != 0:
            sys.exit("could not build gpu/gpu_batch_verify")
    return exe


def gpu_info():
    q = "name,memory.total,compute_cap,driver_version,clocks.sm,clocks.max.sm,clocks.mem,power.limit,persistence_mode"
    r = subprocess.run(["nvidia-smi", "--query-gpu=" + q, "--format=csv"], capture_output=True, text=True)
    out = os.path.join(TOP, "results", "gpu_info.csv")
    with open(out, "w") as f:
        f.write(r.stdout)
    lines = r.stdout.strip().splitlines()
    mem_mib = 0
    if len(lines) > 1:
        try:
            mem_mib = int(lines[1].split(",")[1].strip().split()[0])
        except (IndexError, ValueError):
            pass
    return mem_mib


def sizes(cpu_dir):
    r = subprocess.run([os.path.join(cpu_dir, "bench"), "sizes"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split(",")
        if p[0] == "SIZES":
            return int(p[5]), int(p[7])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", action="append", default=[])
    ap.add_argument("--match", default="")
    ap.add_argument("--category")
    ap.add_argument("--cpu-platform", default="x86")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--batches", default=",".join(str(b) for b in BATCHES))
    ap.add_argument("--modes", default="shared,distinct")
    ap.add_argument("--tpb", type=int, default=128)
    ap.add_argument("--heap-mb", type=int, default=4096)
    ap.add_argument("--chunk", type=int, default=0, help="signatures per launch; 0 = whole batch")
    ap.add_argument("--stack-margin", type=float, default=1.0,
                    help="stack limit = ptxas cumulative stack x this + 1 KiB; the ptxas figure is exact without recursion")
    ap.add_argument("--max-dump-gb", type=float, default=8.0)
    ap.add_argument("--threads", type=int, default=os.cpu_count())
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--batch-budget-s", type=float, default=2400,
                    help="largest predicted time for one batch size (warm-up + reps); the prediction is the next "
                         "batch at the best rate seen so far in that mode. Fewer reps when needed, a SKIP,time_budget "
                         "row when not even one rep fits")
    a = ap.parse_args()

    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    built = {}
    for n in sorted(recipes):
        j = os.path.join(TOP, "build", "gpu", n, "gpu_build.json")
        if os.path.exists(j):
            built[n] = json.load(open(j))
    names = a.recipe or [n for n in built if a.match in n]
    if a.category and not a.recipe:
        names = [n for n in names if category(recipes[n]) == a.category]
    okset = kat_ok(a.cpu_platform)
    exe = host_program()
    os.makedirs(os.path.join(TOP, "results"), exist_ok=True)
    mem_mib = gpu_info()
    raw = os.path.join(TOP, "results", "raw", "gpu")
    dumps = os.path.join(TOP, "build", "gpu_dumps")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(dumps, exist_ok=True)

    for n in names:
        rec = recipes[n]
        b = built.get(n)
        out = os.path.join(raw, "batch_%s.csv" % n)
        if not b or b.get("status") != "ok":
            print("skip %-40s GPU build status: %s" % (n, b.get("status") if b else "not built"))
            continue
        if n not in okset:
            print("skip %-40s no passing KAT row on %s" % (n, a.cpu_platform))
            continue
        if not a.force and os.path.exists(out) and "GPU_DONE" in open(out).read():
            print("skip %-40s already measured (use --force to redo)" % n)
            continue
        cpu_dir = os.path.join(TOP, "build", a.cpu_platform, n)
        if not os.path.exists(os.path.join(cpu_dir, "batch_tls.ok")):
            r = subprocess.run([sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", n,
                                "--platform", a.cpu_platform], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(os.path.join(cpu_dir, "cpu_batch_verify")):
                print("skip %-40s cpu_batch_verify did not build on %s" % (n, a.cpu_platform))
                continue
        sz = sizes(cpu_dir)
        if not sz:
            print("skip %-40s no SIZES row" % n)
            continue
        pklen, siglen = sz
        smmax = MLEN + siglen
        stack = int(b["stack_bound"] * a.stack_margin) + 1024
        label = "%s,%s,%s" % (rec["scheme"], rec["param"], rec["variant"])
        cubin = os.path.join(TOP, "build", "gpu", n, "pq_verify.cubin")
        print("== %s  stack %d B, regs %s" % (n, stack, b.get("registers")), flush=True)
        # Resume inside a recipe after a cut: batch sizes that already have
        # all their BATCH rows are kept, and their best rate seeds the budget.
        have, best = {}, {}
        if not a.force and os.path.exists(out):
            for l in open(out):
                q = l.strip().split(",")
                if q[0] == "BATCH" and len(q) >= 13:
                    k = (q[6], int(q[8]))
                    have[k] = have.get(k, 0) + 1
                    best[q[6]] = max(best.get(q[6], 0.0), float(q[11]))
        resume = bool(have)
        with open(out, "a" if resume else "w") as f:
            if resume:
                f.write("NOTE,resumed_after_cut,%s\n" % ";".join("%s:%d" % k for k in sorted(have)))
            else:
                f.write("GPU_BUILD,%s,registers,%s,stack_bound,%d,stack_dynamic,%d,mutable_globals,%s\n" % (
                    label, b.get("registers"), b["stack_bound"], int(b.get("stack_dynamic", False)),
                    ";".join(b.get("mutable_globals", [])) or "-"))
            stop_recipe = False
            for mode in a.modes.split(","):
                if stop_recipe:
                    break
                for bn in [int(x) for x in a.batches.split(",")]:
                    if have.get((mode, bn), 0) >= 1:
                        print("  %-8s %6d  kept from the earlier start" % (mode, bn), flush=True)
                        continue
                    reps = a.reps
                    if best.get(mode):
                        t_run = bn / best[mode]
                        fit = int(a.batch_budget_s // t_run) - 1      # one warm-up run first
                        if fit < 1:
                            f.write("SKIP,time_budget,%s,%s,%d,predicted_s_per_run,%.0f\n" % (label, mode, bn, t_run))
                            print("  %-8s %6d  skipped: one run would take about %.0f s" % (mode, bn, t_run), flush=True)
                            break
                        if fit < reps:
                            reps = fit
                            f.write("NOTE,reps_reduced,%s,%s,%d,reps,%d,predicted_s_per_run,%.0f\n" % (
                                label, mode, bn, reps, t_run))
                    nkeys = bn if mode == "distinct" else 1
                    dump_bytes = 48 + nkeys * pklen + bn * (8 + smmax + 1 + MLEN)
                    if dump_bytes > a.max_dump_gb * 2**30:
                        f.write("SKIP,dump_too_large,%s,%s,%d,%d\n" % (label, mode, bn, dump_bytes))
                        print("  %-8s %6d  skipped: batch file %.1f GB" % (mode, bn, dump_bytes / 2**30), flush=True)
                        break
                    dump = os.path.join(dumps, "%s_%s_%d.bin" % (n, mode, bn))
                    env = dict(os.environ, BATCH_DUMP=dump)
                    c = subprocess.run([os.path.join(cpu_dir, "cpu_batch_verify"), mode, str(bn), "1", str(a.threads)],
                                       env=env, capture_output=True, text=True)
                    if c.returncode != 0 or not os.path.exists(dump):
                        f.write("ERROR,cpu_dump,%s,%s,%d,%s\n" % (label, mode, bn, (c.stdout + c.stderr).strip().replace("\n", " ")[-120:]))
                        break
                    # A kernel fault is often the device heap running out when
                    # every resident thread allocates at once (FAEST, MQOM):
                    # retry with fewer signatures per launch.
                    for ch in ([a.chunk] if a.chunk else [0, 16384, 2048, 256]):
                        if ch and ch >= bn and ch != a.chunk:
                            continue
                        g = subprocess.run([exe, cubin, dump, str(reps), "--label", label, "--tpb", str(a.tpb),
                                            "--stack", str(stack), "--heap-mb", str(a.heap_mb), "--chunk", str(ch)],
                                           capture_output=True, text=True)
                        lines = g.stdout.splitlines()
                        wrong = any(l.startswith("BATCH,") and l.endswith(",0") for l in lines)
                        if not any(l.startswith("ERROR,kernel") for l in lines) and not wrong:
                            break
                        if wrong and bn <= 256:
                            break      # a real mismatch, not the device heap: keep it
                        f.write("RETRY,%s,%s,%s,%d,chunk,%d\n" % ("wrong_results" if wrong else "kernel",
                                                                   label, mode, bn, ch))
                    os.remove(dump)
                    f.write(g.stdout)
                    f.flush()
                    errs = [l for l in g.stdout.splitlines() if l.startswith("ERROR")]
                    oks = [l.split(",")[-1] for l in g.stdout.splitlines() if l.startswith("BATCH,")]
                    rate = [float(l.split(",")[-2]) for l in g.stdout.splitlines() if l.startswith("BATCH,")]
                    if rate:
                        best[mode] = max(best.get(mode, 0.0), max(rate))
                    msg = errs[0] if errs else "%.0f verifies/s, all_ok=%s" % (max(rate) if rate else 0, ",".join(oks))
                    print("  %-8s %6d  %s" % (mode, bn, msg), flush=True)
                    if errs:
                        if "stack_limit" in errs[0] or "heap_limit" in errs[0] or "module_load" in errs[0]:
                            stop_recipe = True
                        break
            f.write("GPU_DONE,%s\n" % label)
    if mem_mib:
        print("GPU memory %d MiB; details in results/gpu_info.csv" % mem_mib)


if __name__ == "__main__":
    main()
