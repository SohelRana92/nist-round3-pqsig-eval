#!/usr/bin/env python3
"""build_gpu.py - build the GPU batch-verification kernel of a recipe.

  python3 gpu/build_gpu.py --recipe uov-Ip_pkc-ref-portable
  python3 gpu/build_gpu.py --category 1            # every portable Category 1 recipe
  python3 gpu/build_gpu.py --list                  # recipes it would build

Steps for one recipe
  1. tools/hbuild.py --platform gpu builds the recipe for the host with
     gpu/cc_gpu.py as the compiler, which also writes NVPTX bitcode
     (file.o.nvbc) for every C file, the teams' make and CMake builds
     included.
  2. The bitcode of exactly the objects in libscheme.a (matched by file
     content), of the harness objects (SHAKE, AES helpers), of
     gpu/libc_gpu.c and of gpu/kernel.c are linked with llvm-link. The
     library files are linked with --only-needed, three passes, which
     gives the same symbol choice as a static archive.
  3. opt internalises everything except the kernel pq_verify and runs -O3,
     so code that verification does not reach disappears.
  4. llc writes PTX; ptxas -arch=sm_120 turns it into a cubin for the
     RTX 5070 Ti and reports registers and stack frame per thread.

Output in build/gpu/<recipe>/:
  pq_verify.ptx, pq_verify.cubin, gpu_build.json, gpu_build.log
gpu_build.json records the tool versions, registers, stack frame, any
mutable global variable (state shared by all threads: the result check
in gpu_batch_verify then decides whether it matters) and, on failure,
the reason.

Only portable C recipes are built: the GPU runs the same code as the
ESP32 (ref, ref-portable, opt-portable, SNOVA opt, mem, tiny). Platform
intrinsics (AVX2, NEON) do not exist on the GPU.

Environment: PQSIG_GPU_CLANG, PQSIG_GPU_LLVM_SUFFIX (for example -18),
PQSIG_GPU_PTXAS (default: ptxas on PATH, then /usr/local/cuda/bin/ptxas),
PQSIG_GPU_SM (default sm_120).
"""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TOP, "tools"))
from kat_all import category  # noqa: E402

PORTABLE = {"ref", "ref-portable", "opt-portable", "mem", "tiny"}
# Reached in harness/common but not by any verification routine.
SKIP_HARNESS = ("h_nist_rng.o", "h_pqclean_randombytes.o")
SYSCALLS = {"malloc", "free", "vprintf"}


def gpu_recipe(rec):
    v = rec.get("variant", "")
    return v in PORTABLE or (rec.get("scheme") == "SNOVA" and v == "opt")


def tool(name):
    suf = os.environ.get("PQSIG_GPU_LLVM_SUFFIX")
    cands = [name + suf] if suf else [name] + [name + "-%d" % v for v in range(22, 16, -1)]
    for c in cands:
        if shutil.which(c):
            return c
    sys.exit("%s not found: sudo apt install clang llvm (or set PQSIG_GPU_LLVM_SUFFIX)" % name)


def ptxas():
    p = os.environ.get("PQSIG_GPU_PTXAS") or shutil.which("ptxas")
    for c in ([p] if p else []) + ["/usr/local/cuda/bin/ptxas"] + sorted(glob.glob("/usr/local/cuda-*/bin/ptxas"), reverse=True):
        if c and os.path.exists(c):
            return c
    sys.exit("ptxas not found: install the CUDA toolkit or set PQSIG_GPU_PTXAS")


def run(cmd, log, **kw):
    log.write("+ " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    log.write(r.stdout + r.stderr)
    log.flush()
    return r


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def first_line(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()[0]
    except Exception:
        return "?"


def nm(path):
    """(defined, undefined) global symbols of a bitcode file."""
    d, u = set(), set()
    out = subprocess.run([tool("llvm-nm"), path], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        t, sym = parts[-2], parts[-1]
        if t == "U":
            u.add(sym)
        elif t in "TDBRWVC":
            d.add(sym)
    return d, u


def select_modules(first, mods):
    tab = {m: nm(m) for m in mods}
    have, need = nm(first)
    need = set(need)
    chosen = []
    changed = True
    while changed:
        changed = False
        for m in mods:
            if m in chosen:
                continue
            d, u = tab[m]
            if d & (need - have):
                chosen.append(m)
                have |= d
                need |= u
                changed = True
    return chosen


def build_one(name, rec, clang, sm, log):
    out = os.path.join(TOP, "build", "gpu", name)
    lists = os.path.join(TOP, "build", "gpu", ".lists")
    os.makedirs(lists, exist_ok=True)
    lst = os.path.join(lists, name + ".tsv")
    if os.path.exists(lst):
        os.remove(lst)
    env = dict(os.environ)
    env["PQSIG_GPU_LIST"] = lst
    env["PQSIG_GPU_CLANG"] = clang
    r = run([sys.executable, os.path.join(TOP, "tools", "hbuild.py"), "--recipe", name, "--platform", "gpu"], log, env=env)
    if r.returncode != 0:
        return {"status": "host_build_failed"}
    shutil.move(lst, os.path.join(out, "nvbc_list.tsv"))
    entries = [l.rstrip("\n").split("\t") for l in open(os.path.join(out, "nvbc_list.tsv"))]
    by_hash = {}
    for obj, bc, status, src in entries:
        if os.path.exists(obj):
            by_hash.setdefault(sha(obj), (bc, status, src))
    info = json.load(open(os.path.join(out, "build.json")))

    # 2a. scheme objects: libscheme.a members matched by content
    tmp = tempfile.mkdtemp(prefix="arx_", dir=out)
    subprocess.run(["ar", "x", os.path.join(out, "libscheme.a")], cwd=tmp, check=True)
    lib_bc, missing = [], []
    for m in sorted(os.listdir(tmp)):
        hit = by_hash.get(sha(os.path.join(tmp, m)))
        if hit and hit[1] == "ok":
            lib_bc.append(hit[0])
        else:
            missing.append({"object": m, "source": hit[2] if hit else "?",
                            "log": (hit[0] + ".log") if hit else ""})
    shutil.rmtree(tmp)
    # 2b. harness objects (SHAKE and similar helpers shared by recipes)
    h_bc = [bc for obj, bc, status, src in entries
            if os.path.basename(obj).startswith("h_") and os.path.basename(obj) not in SKIP_HARNESS
            and status == "ok" and os.path.dirname(obj) == os.path.join(out, "obj")]

    # 2c. kernel and C library, with the recipe's defines and includes
    base = [clang, "--target=nvptx64-nvidia-cuda", "-march=sm_89", "-O3", "-emit-llvm", "-c",
            "-nostdlibinc", "-isystem", os.path.join(HERE, "include"), "-DPQSIG_GPU=1"]
    defs = ["-D" + d for d in info.get("defines", []) + info.get("bench_defines", [])]
    incs = ["-I" + d for d in info.get("includes", [])]
    k_bc = os.path.join(out, "kernel.nvbc")
    c_bc = os.path.join(out, "libc_gpu.nvbc")
    # With the package's api.h when it compiles for the GPU, as bench_main.c
    # uses it; otherwise with the plain NIST prototype.
    if run(base + defs + incs + ["-DPQG_HAVE_API=1", os.path.join(HERE, "kernel.c"), "-o", k_bc], log).returncode != 0:
        if run(base + defs + incs + [os.path.join(HERE, "kernel.c"), "-o", k_bc], log).returncode != 0:
            return {"status": "kernel_compile_failed"}
    if run(base + ["-ffreestanding", "-fno-builtin", os.path.join(HERE, "libc_gpu.c"), "-o", c_bc], log).returncode != 0:
        return {"status": "libc_compile_failed"}

    # 2d. link with static-archive semantics: starting from the kernel,
    #     take the first module that defines a still-undefined symbol, and
    #     repeat until nothing changes.
    linked = os.path.join(out, "linked.bc")
    libs = lib_bc + h_bc + [c_bc]
    chosen = select_modules(k_bc, libs)
    r = run([tool("llvm-link"), k_bc] + chosen + ["-o", linked], log)
    if r.returncode != 0:
        return {"status": "link_failed", "missing_bitcode": missing, "detail": r.stderr[-500:]}

    # 3. internalise and optimise
    opt_bc = os.path.join(out, "pq_verify.bc")
    r = run([tool("opt"), "-passes=internalize,globaldce,default<O3>,globaldce",
             "-internalize-public-api-list=pq_verify", linked, "-o", opt_bc], log)
    if r.returncode != 0:
        return {"status": "opt_failed", "detail": r.stderr[-500:]}
    ll = subprocess.run([tool("llvm-dis"), opt_bc, "-o", "-"], capture_output=True, text=True).stdout
    undefined = sorted(set(re.findall(r"^declare [^@]*@([A-Za-z_][\w.$]*)\(", ll, re.M))
                       - SYSCALLS - {n for n in re.findall(r"@(llvm\.[\w.]+)", ll)})
    undefined = [u for u in undefined if not u.startswith("llvm.")]
    mutable = sorted(set(re.findall(r"^@([\w.$]+) = (?:internal |private |dso_local )*(?:unnamed_addr |local_unnamed_addr )*(?:addrspace\(\d\) )?global ", ll, re.M)))
    if undefined:
        return {"status": "unresolved_symbols", "unresolved": undefined, "missing_bitcode": missing}

    # 4. PTX and cubin
    ptx = os.path.join(out, "pq_verify.ptx")
    r = run([tool("llc"), "-march=nvptx64", "-mcpu=sm_89", "-O3", opt_bc, "-o", ptx], log)
    if r.returncode != 0:
        return {"status": "llc_failed", "detail": r.stderr[-500:]}
    cubin = os.path.join(out, "pq_verify.cubin")
    r = run([ptxas(), "-arch=" + sm, "-O3", "-v", ptx, "-o", cubin], log)
    if r.returncode != 0:
        return {"status": "ptxas_failed", "detail": r.stderr[-800:]}
    rep = r.stdout + r.stderr
    frames = {f: int(b) for f, b in re.findall(r"Function properties for (\S+)\s*\n\s*(\d+) bytes stack frame", rep)}
    m = re.search(r"Compiling entry function 'pq_verify'.*?Used (\d+) registers.*?(\d+) bytes cumulative stack size", rep, re.S)
    regs = [m.group(1)] if m else re.findall(r"Compiling entry function 'pq_verify'.*?Used (\d+) registers", rep, re.S)
    dynamic = "cannot be statically determined" in rep
    # ptxas reports the cumulative stack of the whole call tree; with
    # recursion or calls through pointers it cannot, and the sum of all
    # frames is used as a bound.
    stack = int(m.group(2)) if m and not dynamic else sum(frames.values())
    return {"status": "ok", "registers": int(regs[0]) if regs else None,
            "stack_frame_kernel": frames.get("pq_verify", 0), "stack_bound": stack,
            "stack_dynamic": dynamic, "functions_not_inlined": len(frames) - 1 if frames else 0,
            "mutable_globals": mutable, "missing_bitcode_unused": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", action="append", default=[])
    ap.add_argument("--match", default="")
    ap.add_argument("--category")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="recipes built at once; ptxas needs up to about 3 GB per large kernel")
    a = ap.parse_args()
    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    if a.recipe:
        names = a.recipe
    else:
        names = [n for n in sorted(recipes) if gpu_recipe(recipes[n]) and a.match in n]
        if a.category:
            names = [n for n in names if category(recipes[n]) == a.category]
    if a.list:
        print("\n".join(names))
        return
    clang = os.environ.get("PQSIG_GPU_CLANG") or tool("clang")
    sm = os.environ.get("PQSIG_GPU_SM", "sm_120")
    pv = subprocess.run([ptxas(), "--version"], capture_output=True, text=True).stdout.strip().splitlines()
    versions = {"clang": first_line([clang, "--version"]), "ptxas": pv[-1] if pv else "?", "sm": sm}
    summary = []
    os.makedirs(os.path.join(TOP, "build", "gpu"), exist_ok=True)
    jobs = [(n, recipes[n], clang, sm, versions) for n in names]
    if a.jobs > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
            for res in ex.map(build_and_record, jobs):
                report(res)
                summary.append(res)
    else:
        for j in jobs:
            res = build_and_record(j)
            report(res)
            summary.append(res)
    os.makedirs(os.path.join(TOP, "results"), exist_ok=True)
    sp = os.path.join(TOP, "results", "gpu_build_summary.json")
    old = {}
    if os.path.exists(sp):
        old = {r["recipe"]: r for r in json.load(open(sp))}
    for r in summary:
        old[r["recipe"]] = r
    with open(sp, "w") as f:
        json.dump([old[k] for k in sorted(old)], f, indent=1)


def build_and_record(job):
    n, rec, clang, sm, versions = job
    out = os.path.join(TOP, "build", "gpu", n)
    logp = os.path.join(TOP, "build", "gpu", n + ".log")
    with open(logp, "w") as log:
        res = build_one(n, rec, clang, sm, log)
    res.update({"recipe": n, "scheme": rec["scheme"], "param": rec["param"],
                "variant": rec["variant"], "tools": versions})
    if os.path.isdir(out):
        shutil.move(logp, os.path.join(out, "gpu_build.log"))
        with open(os.path.join(out, "gpu_build.json"), "w") as f:
            json.dump(res, f, indent=2)
    return res


def report(res):
    if True:
        n = res["recipe"]
        extra = ""
        if res["status"] == "ok":
            extra = "regs=%s stack=%d B%s%s" % (res["registers"], res["stack_bound"],
                                               " dynamic" if res["stack_dynamic"] else "",
                                               " MUTABLE:" + ",".join(res["mutable_globals"][:4]) if res["mutable_globals"] else "")
        elif res.get("unresolved"):
            extra = "needs: " + ",".join(res["unresolved"][:6])
        print("%-38s %-20s %s" % (n, res["status"], extra), flush=True)


if __name__ == "__main__":
    main()
