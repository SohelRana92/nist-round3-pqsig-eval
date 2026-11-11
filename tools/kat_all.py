#!/usr/bin/env python3
"""kat_all.py - build recipes and check each against its known answers.

Usage:
  tools/kat_all.py --platform pi5 --category 1          all Category 1 recipes
  tools/kat_all.py --platform x86 --match faest          recipes whose name contains 'faest'
  tools/kat_all.py --platform pi5 --category 1 --set-root UOV=/path/Reference_Implementation

Writes results/kat_<platform>.csv with one row per recipe:
  recipe,scheme,param,variant,platform,method,status,detail
status is PASS, FAIL, BUILD_FAIL or EXTERNAL (checked by the library's
own test suite; see 'detail').

A scheme that fails its KAT on a platform gets no timing on that
platform.
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
from hbuild import source_roots, expand  # noqa: E402
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)

CAT_RULES = {
    "UOV": lambda p: "1" if p.startswith("I") and not p.startswith("III") else ("3" if p.startswith("III") else "5"),
    "MAYO": lambda p: {"MAYO_1": "1", "MAYO_2": "1", "MAYO_3": "3", "MAYO_5": "5"}[p],
    "SQIsign": lambda p: {"p324_3": "1", "p500_27": "3", "p664_17": "5"}[p],
    "SDitH": lambda p: p[3],
    "MQOM": lambda p: p[3],
    "FAEST": lambda p: {"128": "1", "192": "3", "256": "5"}[re.search(r"(128|192|256)", p).group(1)],
    "SNOVA": lambda p: {"I": "1", "III": "3", "V": "5"}[p.split("_")[1]],
    "QR-UOV": lambda p: p[0],
}


def category(rec):
    f = CAT_RULES.get(rec["scheme"])
    return f(rec["param"]) if f else "1"   # baselines are Category 1 sets


# Binaries built for another architecture run under user-mode QEMU.
RUNNER = {"pi5-qemu": ["qemu-aarch64"]}
PREFIX = []


def run(cmd, cwd=None, timeout=None):
    if PREFIX and cmd and cmd[0].startswith(os.path.join(TOP, "build")):
        cmd = PREFIX + cmd
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def build(name, platform, sets):
    cmd = [sys.executable, os.path.join(HERE, "hbuild.py"), "--recipe", name, "--platform", platform]
    for s in sets:
        cmd += ["--set", s]
    r = run(cmd)
    return r.returncode == 0, (r.stdout + r.stderr)[-400:]


def bdir(platform, name):
    return os.path.join(TOP, "build", platform, name)


# Temp folders made for one recipe; removed after its check. A 100-vector
# .rsp of UOV-III or UOV-V is hundreds of MB, and /tmp is often a RAM disk.
TEMP_DIRS = []
KAT_TMP = os.path.join(TOP, "build", "kat_tmp")


def cleanup_temp():
    while TEMP_DIRS:
        shutil.rmtree(TEMP_DIRS.pop(), ignore_errors=True)


def file_digest(path, m):
    h = hashlib.shake_256() if m == "shake24" else hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(24) if m == "shake24" else h.hexdigest()


def genkat(platform, name):
    """Run the recipe's genkat in a temp dir and return the .rsp path."""
    d = tempfile.mkdtemp(prefix="kat_", dir=KAT_TMP)
    TEMP_DIRS.append(d)
    exe = os.path.join(bdir(platform, name), "genkat")
    run([exe], cwd=d, timeout=7200)
    rsp = glob.glob(os.path.join(d, "*.rsp"))
    return rsp[0] if rsp else None


def check(name, rec, platform, n_vectors):
    roots = source_roots()
    k = {key: (expand(v, roots) if isinstance(v, str) else v) for key, v in rec.get("kat", {}).items()}
    m = k.get("method")
    bench = os.path.join(bdir(platform, name), "bench")
    if m == "rsp":
        files = glob.glob(k["rsp"])
        if not files:
            return "FAIL", "reference .rsp not found: " + k["rsp"]
        out = run([bench, "kat", str(n_vectors)], timeout=7200).stdout
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv")
        tmp.write(out)
        tmp.close()
        r = run([sys.executable, os.path.join(TOP, "kat", "check_kat.py"), files[0], tmp.name])
        os.unlink(tmp.name)
        return ("PASS" if r.returncode == 0 else "FAIL"), r.stdout.strip().splitlines()[-1]
    if m in ("shake24", "sha256"):
        rsp = genkat(platform, name)
        if not rsp:
            return "FAIL", "genkat produced no .rsp"
        got = file_digest(rsp, m)
        exp = None
        for line in open(k["list"]):
            line = line if line.endswith("\n") else line + "\n"
            if m == "shake24" and line.split() and line.split()[0] == k["key"]:
                exp = line.split()[1]
            if m == "sha256" and k["key"] in line:
                exp = line.split()[0]
        if exp is None:
            return "FAIL", "no published digest for " + k["key"]
        return ("PASS" if got == exp else "FAIL"), "%s of 100-vector .rsp %s published value" % (m, "matches" if got == exp else "differs from")
    if m == "compare_recipe":
        other = k["with"]
        a = run([bench, "kat", str(n_vectors)], timeout=7200).stdout
        # KAT output does not depend on the platform, so when the reference
        # recipe cannot be built here (OpenSSL missing on a 32-bit build, say)
        # its output from a native build serves as the reference.
        ref_plat = next((q for q in (platform, "x86", "x86-generic", "pi5")
                         if os.path.exists(os.path.join(bdir(q, other), "bench"))), None)
        if ref_plat is None:
            return "FAIL", "reference recipe %s has no build on this or a native platform" % other
        b = run([os.path.join(bdir(ref_plat, other), "bench"), "kat", str(n_vectors)], timeout=7200).stdout
        strip = lambda s: [",".join(l.split(",")[5:]) for l in s.splitlines() if l.startswith("KAT,")]
        same = strip(a) == strip(b) and len(strip(a)) == n_vectors
        return ("PASS" if same else "FAIL"), "%d vectors %s %s (%s build)" % (
            n_vectors, "identical to" if same else "differ from", other, ref_plat)
    if m == "pqclean":
        b = bdir(platform, name)
        exe = os.path.join(b, "pqclean_nistkat")
        src = os.path.join(roots["SRC"], "pqclean", "test", "crypto_sign", "nistkat.c")
        objs = glob.glob(os.path.join(b, "obj", "h_*.o"))
        cc = "aarch64-linux-gnu-gcc" if platform == "pi5-qemu" else ("gcc -m32".split() if platform == "x86-32" else "gcc")
        cc = cc if isinstance(cc, list) else [cc]
        r = run(cc + ["-O2", "-std=c99"] + (["-static"] if platform == "pi5-qemu" else []) + [ "-I" + os.path.join(TOP, "harness", "common"), "-I" + os.path.join(b, "src"),
                 "-DPQCLEAN_NAMESPACE=" + k["namespace"], src, os.path.join(TOP, "kat", "pqclean_nist_kat_init.c"),
                 os.path.join(b, "libscheme.a")] + objs + ["-o", exe])
        if r.returncode != 0:
            return "FAIL", "could not build PQClean nistkat"
        got = hashlib.sha256(run([exe]).stdout.encode()).hexdigest()
        exp = re.search(r"nistkat-sha256:\s*([0-9a-f]+)", open(k["meta"]).read()).group(1)
        return ("PASS" if got == exp else "FAIL"), "PQClean nistkat-sha256 " + ("matches" if got == exp else "differs")
    if m == "upstream_test":
        # Exit status 0 from the package's own test program, which checks
        # its built-in known-answer hashes, and a clean harness round trip.
        r = run([os.path.join(bdir(platform, name), "upstream_test")], timeout=7200)
        out = run([bench, "kat", str(n_vectors)], timeout=7200).stdout
        rt = all(l.split(",")[-1] == "1" for l in out.splitlines() if l.startswith("KAT,"))
        ok = r.returncode == 0 and rt
        return ("PASS" if ok else "FAIL"), k["note"] + (" passed" if r.returncode == 0 else " FAILED (exit %d)" % r.returncode) + \
            ("; harness round trip ok" if rt else "; round trip FAILED")
    if m == "external":
        out = run([bench, "kat", str(n_vectors)], timeout=7200).stdout
        ok = all(l.split(",")[-1] == "1" for l in out.splitlines() if l.startswith("KAT,"))
        return ("EXTERNAL" if ok else "FAIL"), k["note"] + ("; harness round trip ok" if ok else "; round trip FAILED")
    if m == "self_genkat_note":
        out = run([bench, "kat", str(n_vectors)], timeout=7200).stdout
        ok = all(l.split(",")[-1] == "1" for l in out.splitlines() if l.startswith("KAT,"))
        return ("EXTERNAL" if ok else "FAIL"), k["note"]
    return "FAIL", "no KAT method in recipe"


def write_rows(outp, rows):
    """Merge into the existing CSV: a rerun with --match replaces only the
    rows of the recipes it ran. Written after every recipe."""
    # Several kat_all.py runs (one per category) may share this file, so
    # the read-merge-write is done under an exclusive lock.
    import fcntl
    lock = open(outp + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    keep = {}
    if os.path.exists(outp):
        with open(outp, newline="") as f:
            for r in list(csv.reader(f))[1:]:
                if r:
                    keep[r[0]] = r
    for r in rows:
        keep[r[0]] = r
    tmp = outp + ".tmp%d" % os.getpid()
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipe", "scheme", "param", "variant", "platform", "method", "status", "detail"])
        w.writerows(keep[k] for k in sorted(keep))
    os.replace(tmp, outp)
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="pi5")
    ap.add_argument("--category", default=None, help="1, 3 or 5")
    ap.add_argument("--match", default="")
    ap.add_argument("--vectors", type=int, default=5)
    ap.add_argument("--set", action="append", default=[], help="passed to hbuild.py")
    ap.add_argument("--resume", action="store_true",
                    help="skip recipes that already have a PASS or EXTERNAL row in results/kat_<platform>.csv "
                         "(after a power cut)")
    ap.add_argument("--clean", action="store_true",
                    help="delete each recipe's build folder after it passes (saves disk)")
    a = ap.parse_args()
    PREFIX[:] = RUNNER.get(a.platform, [])

    recipes = json.load(open(os.path.join(TOP, "registry", "recipes.json")))["recipes"]
    names = [n for n in sorted(recipes) if a.match in n]
    if a.category:
        names = [n for n in names if category(recipes[n]) == a.category]
    # Optimised recipes name the platforms they are written for.
    names = [n for n in names if a.platform in recipes[n].get("platforms", [a.platform])]
    # Build compare targets first.
    order = sorted(names, key=lambda n: 0 if recipes[n].get("kat", {}).get("method") != "compare_recipe" else 1)
    os.makedirs(os.path.join(TOP, "results"), exist_ok=True)
    os.makedirs(KAT_TMP, exist_ok=True)
    outp = os.path.join(TOP, "results", "kat_%s.csv" % a.platform)
    rows = []
    passed = set()
    if a.resume and os.path.exists(outp):
        with open(outp) as f:
            for r in csv.reader(f):
                if len(r) > 6 and r[6] in ("PASS", "EXTERNAL"):
                    passed.add(r[0])
    for n in order:
        rec = recipes[n]
        if n in passed:
            print("%-36s %-10s %s" % (n, "skip", "already passed"), flush=True)
            continue
        dep = rec.get("kat", {}).get("with")
        if dep and not os.path.exists(os.path.join(bdir(a.platform, dep), "bench")):
            build(dep, a.platform, a.set)
        ok, log = build(n, a.platform, a.set)
        if not ok:
            st, det = "BUILD_FAIL", log.replace("\n", " ")[-200:]
        else:
            try:
                st, det = check(n, rec, a.platform, a.vectors)
            except subprocess.TimeoutExpired:
                st, det = "FAIL", "timeout"
            except FileNotFoundError as e:
                st, det = "FAIL", "missing program: %s" % e.filename
        cleanup_temp()
        rows.append([n, rec["scheme"], rec["param"], rec["variant"], a.platform,
                     rec.get("kat", {}).get("method", ""), st, det])
        print("%-36s %-10s %s" % (n, st, det), flush=True)
        write_rows(outp, rows)
        if a.clean and st in ("PASS", "EXTERNAL"):
            # run_bench.py rebuilds every recipe, so a passed build can go.
            shutil.rmtree(bdir(a.platform, n), ignore_errors=True)
    print("wrote", outp if rows else "nothing (no recipe matched)")
    sys.exit(0 if all(r[6] in ("PASS", "EXTERNAL") for r in rows) else 1)


if __name__ == "__main__":
    main()
