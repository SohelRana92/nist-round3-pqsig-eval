#!/usr/bin/env python3
"""hbuild.py - build one scheme/parameter set for Linux (Raspberry Pi 5 or
the Ryzen 9 9950X) from a recipe in registry/recipes.json.

What it builds, under build/<platform>/<scheme>-<param>-<variant>/:
  libscheme.a   the scheme's own objects only (for code/RAM size)
  size.txt      `size -t` over those objects
  bench         harness driver linked with libscheme.a
  genkat        the package's own PQCgenKAT_sign.c, linked with the
                harness DRBG, when the recipe names one
  build.json    exact sources, flags and compiler version used

Usage:
  tools/hbuild.py --recipe uov-Ip-ref-nist --platform pi5
  tools/hbuild.py --recipe uov-Ip-ref-nist --platform x86 --set ROOT=/path/to/pqov
  tools/hbuild.py --list

A recipe's paths use ${VAR} names. Each VAR has a default in the
recipe's "vars" block and can be overridden with --set VAR=value.
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
HARNESS = os.path.join(TOP, "harness")

PLATFORM_FLAGS = {
    # -march=native is avoided on purpose: the flags must be written into
    # the paper exactly. Cortex-A76 is the Raspberry Pi 5 core. znver5 is
    # the Ryzen 9 9950X core and needs GCC 14 or newer.
    # The BCM2712 in the Pi 5 has the ARMv8 Cryptography Extension, so
    # +crypto is part of the target description, not an extra option.
    "pi5": ["-O3", "-mcpu=cortex-a76+crypto"],
    # Same target, cross-compiled here and run under qemu-aarch64 for KAT
    # checks only (never for timing).
    "pi5-qemu": ["-O3", "-mcpu=cortex-a76+crypto"],
    "x86": ["-O3", "-march=znver5"],
    "x86-generic": ["-O3", "-march=x86-64-v3"],   # for this build server only
    # Cross targets: hbuild only stages sources and writes manifest.json.
    # esp32/make_project.py and fpga/make_vitis_app.py consume it.
    # 32-bit Linux build for portability tests on a PC: same pointer and
    # size_t width as the ESP32 and MicroBlaze. Never used for results.
    "x86-32": ["-O3", "-m32"],
    "esp32": ["-O3"],
    "microblaze": ["-O3"],
    # Host build whose compiler wrapper (gpu/cc_gpu.py) also writes NVPTX
    # bitcode for every C file; gpu/build_gpu.py turns that into the GPU
    # verification kernel. The host objects themselves are not measured.
    "gpu": ["-O2"],
}
CROSS = ("esp32", "microblaze")
# Recipe keys such as source_dirs_pi5 are looked up under this name.
KEY_ALIAS = {"pi5-qemu": "pi5"}
PLATFORM_CC = {"pi5-qemu": "aarch64-linux-gnu-gcc",
               "gpu": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gpu", "cc_gpu.py")}
PLATFORM_TOOL_PREFIX = {"pi5-qemu": "aarch64-linux-gnu-"}
# Static linking lets qemu-aarch64 run the binaries without a sysroot.
# /opt/arm64-openssl holds a cross-built libcrypto for the -nist recipes.
PLATFORM_INC = {"pi5-qemu": ["/opt/arm64-openssl/include"]}
PLATFORM_LINK = {"pi5-qemu": ["-static", "-L/opt/arm64-openssl/lib64", "-L/opt/arm64-openssl/lib"]}


def sh_soft(cmd, what):
    """Like sh() but a failure only prints a NOTE: the extra programs (ct
    tests, batch driver) must not block the benchmark build."""
    print("+", " ".join(shlex.quote(c) for c in cmd), flush=True)
    if subprocess.run(cmd).returncode != 0:
        print("NOTE: %s did not build on this platform" % what, flush=True)


VG_DROP = ("-mavx512", "-mgfni", "-mvaes", "-mvpclmulqdq", "-mavx10")


def memcheck_lib(a, vflags, cflags, srcs, harness_srcs, defines, inc_flags, out, tp, lib, hobjs, rec=None, env=None):
    """Scheme library and harness objects rebuilt with flags Valgrind 3.22
    can decode, for ct_memcheck only.
    Harness: -march=x86-64-v3 and none of the recipe's AVX-512, GFNI or VAES
    options (the harness DRBG must not stop Valgrind before the scheme runs).
    Scheme: -march=x86-64-v3 with the recipe's own options kept, so variants
    that ask for AVX-512 or GFNI still stop, and run_ct.sh reports that.
    Team builds (make/CMake) are repeated in a copy of the tree without its
    object files."""
    if vflags == cflags:
        return lib, hobjs
    hflags = [f for f in vflags if not f.startswith(VG_DROP)]
    os.makedirs(os.path.join(out, "obj_vg"), exist_ok=True)
    vh = []
    for s_ in harness_srcs:
        o = os.path.join(out, "obj_vg", "h_" + os.path.basename(s_)[:-2] + ".o")
        # Some packages' headers insist on their ISA options (MAYO GFNI);
        # then the harness file is built with the recipe's options.
        for fl in (hflags, vflags, cflags):
            cmd = [a.cc] + fl + defines + inc_flags + ["-c", s_, "-o", o]
            print("+", " ".join(shlex.quote(c) for c in cmd), flush=True)
            if subprocess.run(cmd).returncode == 0:
                break
        else:
            sys.exit("harness file %s did not build" % s_)
        vh.append(o)
    vobjs = []
    if rec is not None and rec.get("external_build"):
        vg = os.path.join(out, "vg")
        shutil.rmtree(vg, ignore_errors=True)
        shutil.copytree(os.path.join(out, "tree"), os.path.join(vg, "tree"),
                        ignore=shutil.ignore_patterns("*.o", "*.a", "CMakeCache.txt", "CMakeFiles"))
        vobjs = external_build(rec["external_build"], env, vg, a, vflags, defines, tp)
    else:
        for i, s_ in enumerate(srcs):
            o = os.path.join(out, "obj_vg", "%03d_%s.o" % (i, os.path.basename(s_)[:-2]))
            sh([a.cc] + vflags + ["-g"] + defines + inc_flags + ["-c", s_, "-o", o])
            vobjs.append(o)
    if not vobjs:
        return lib, vh
    vlib = os.path.join(out, "libscheme_vg.a")
    if os.path.exists(vlib):
        os.remove(vlib)
    sh([tp + "ar", "rcs", vlib] + vobjs)
    return vlib, vh


def sh(cmd, cwd=None):
    print("+", " ".join(shlex.quote(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        sys.exit("command failed with exit code %d" % r.returncode)


def source_roots():
    """${SRC}: the team repositories; ${NIST}: the NIST-layout folders and
    reference KAT files. tools/fetch_sources.sh creates both under
    $PQSIG_SOURCES (default ~/pqsig-src)."""
    root = os.environ.get("PQSIG_SOURCES", os.path.join(os.path.expanduser("~"), "pqsig-src"))
    return {"SRC": os.path.join(root, "src"), "NIST": os.path.join(root, "nist")}


def expand(s, env):
    def rep(m):
        k = m.group(1)
        if k not in env:
            sys.exit("recipe uses ${%s} but no value is set" % k)
        return env[k]
    return re.sub(r"\$\{([A-Za-z0-9_]+)\}", rep, s)


def load_recipes():
    with open(os.path.join(TOP, "registry", "recipes.json")) as f:
        return json.load(f)["recipes"]


def build_batch(a, cflags, defines, bench_defs, ident, inc_flags, harness_srcs, out, lib, hobjs, libs, plink):
    """cpu_batch_verify links its own copy of the harness DRBG, built with
    HARNESS_RNG_TLS (one DRBG state per thread), so it can sign the batch
    inputs on every core. bench, genkat and the ct programs keep hobjs."""
    tobjs = []
    for s, o in zip(harness_srcs, hobjs):
        if os.path.basename(s) == "nist_rng.c":
            t = o[:-2] + "_tls.o"
            sh([a.cc] + cflags + defines + ["-DHARNESS_RNG_TLS"] + inc_flags + ["-c", s, "-o", t])
            tobjs.append(t)
        else:
            tobjs.append(o)
    exe = os.path.join(out, "cpu_batch_verify")
    if os.path.exists(exe):
        os.remove(exe)
    sh_soft([a.cc] + cflags + defines + bench_defs + ident + inc_flags +
            ["-fopenmp", "-DHARNESS_RNG_TLS", os.path.join(TOP, "gpu", "cpu_batch_verify.c"), lib] + tobjs +
            ["-o", exe, "-fopenmp", "-lpthread"] + libs + plink, "cpu_batch_verify")
    if os.path.exists(exe):
        open(os.path.join(out, "batch_tls.ok"), "w").write("cpu_batch_verify signs its inputs on all threads\n")


def stage_tree(rec, env, out):
    """For packages that use relative includes (../aes/x.h): copy the whole
    package tree, minus the 'drop' list, and compile inside the copy.
    'source_dirs' and 'include_dirs' are then relative to the tree."""
    drop = set(rec.get("drop", []))
    src_root = expand(rec["tree"], env)
    if not os.path.isdir(src_root):
        sys.exit("tree not found: " + src_root)
    tree = os.path.join(out, "tree")
    shutil.copytree(src_root, tree, ignore=lambda d, names: [n for n in names if n in drop])
    srcs = []
    dirs = rec.get("source_dirs", []) + rec.get("source_dirs_" + env.get("PLATFORM_KEY", ""), [])
    for d in dirs:
        full = os.path.join(tree, expand(d, env))
        if not os.path.isdir(full):
            sys.exit("source dir not found in tree: " + d)
        # Assembly files are compiled only when the recipe asks for them:
        # several packages ship assembly for other CPUs in the same folders.
        for ext in (("*.c", "*.s", "*.S") if rec.get("asm_sources") else ("*.c",)):
            srcs += sorted(glob.glob(os.path.join(full, ext)))
    incs = [os.path.join(tree, expand(d, env)) for d in dirs]
    incs += [os.path.join(tree, expand(d, env)) for d in rec.get("include_dirs", [])]
    for f in rec.get("extra_sources", []):
        srcs.append(expand(f, env))
    return srcs, incs


def apply_patches(rec, env, out):
    """Text edits to the staged copy, never to the source tree. Each entry
    of 'patch' (or 'patch_<platform>') is {"file", "old", "new"}; the file
    name is looked up in out/src or out/tree. A missing match stops the
    build, so a changed upstream file cannot be patched silently."""
    for p in rec.get("patch", []) + rec.get("patch_" + env.get("PLATFORM_KEY", ""), []):
        hits = glob.glob(os.path.join(out, "src", p["file"])) + \
            glob.glob(os.path.join(out, "tree", "**", p["file"]), recursive=True)
        if not hits:
            sys.exit("patch target not found: " + p["file"])
        for h in hits:
            with open(h) as f:
                text = f.read()
            if p["old"] not in text:
                sys.exit("patch text not found in " + h + ": " + p["old"])
            with open(h, "w") as f:
                f.write(text.replace(p["old"], p["new"]))


def stage_sources(rec, env, out):
    """Copy each source dir's .c and .h files, minus the 'drop' list, into
    out/src. Compiling from this copy matters: C looks for a quoted
    #include in the source file's own folder first, so a dropped header
    left beside the original sources would still be found.
    Returns (sources, include_dirs)."""
    drop = set(rec.get("drop", []))
    stage = os.path.join(out, "src")
    os.makedirs(stage, exist_ok=True)
    srcs = []
    for d in rec.get("source_dirs", []) + rec.get("source_dirs_" + env.get("PLATFORM_KEY", ""), []):
        d = expand(d, env)
        if not os.path.isdir(d):
            sys.exit("source dir not found: " + d)
        for f in sorted(os.listdir(d)):
            full = os.path.join(d, f)
            if not os.path.isfile(full) or f in drop:
                continue
            if f.endswith((".h", ".c", ".inc", ".macros", ".s", ".S")):
                dst = os.path.join(stage, f)
                if os.path.exists(dst):
                    sys.exit("two source dirs both hold " + f)
                shutil.copy2(full, dst)
                only = rec.get("only_sources")
                code = (".c", ".s", ".S") if rec.get("asm_sources") else (".c",)
                if f.endswith(code) and (only is None or f in only):
                    srcs.append(dst)
    for f in rec.get("extra_sources", []):
        srcs.append(expand(f, env))
    incs = [stage] + [expand(d, env) for d in rec.get("include_dirs", [])]
    return srcs, incs


def external_build(ext, env, out, a, cflags, defines, tp):
    """Build with the team's own make or CMake system inside the staged
    tree and return the object files that form libscheme.a.

    make : CFLAGS goes in through the environment so that the Makefile's
           own "CFLAGS += ..." lines still apply; objects come from the
           Makefile's print_objects target (MQOM).
    cmake: the listed static archives are unpacked; members matching
           'exclude' (the team's randombytes) are left out because the
           harness supplies the NIST DRBG.
    The exact compiler command lines are kept in out/compile_commands.json
    (CMake) or out/make.log (make) for the paper's flag table."""
    tree = os.path.join(out, "tree")
    args = [expand(x, env) for x in ext.get("args", [])]
    targets = [expand(x, env) for x in ext.get("targets", [])]
    excl = ext.get("exclude", [])
    objs = []
    if ext["kind"] == "make":
        e = dict(os.environ)
        e["CC"] = a.cc
        e["CFLAGS"] = " ".join(cflags + defines + ext.get("cflags", []))
        with open(os.path.join(out, "make.log"), "w") as log:
            r = subprocess.run(["make", "-C", tree, "-j2", "CC=" + a.cc] + args + targets,
                               env=e, stdout=log, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            sys.exit("team make failed; see " + os.path.join(out, "make.log"))
        r = subprocess.run(["make", "-s", "--no-print-directory", "-C", tree, "CC=" + a.cc] + args + ["print_objects"],
                           env=e, capture_output=True, text=True)
        for o in r.stdout.split():
            full = os.path.join(tree, o)
            if os.path.exists(full) and not any(fnmatch.fnmatch(os.path.basename(o), x) for x in excl):
                objs.append(full)
        for extra in ext.get("archives", []):
            objs += unpack(os.path.join(tree, expand(extra, env)), out, len(objs), excl, tp)
    elif ext["kind"] == "cmake":
        bdir = os.path.join(out, "cmake")
        cmd = ["cmake", "-S", tree, "-B", bdir, "-DCMAKE_BUILD_TYPE=Release",
               "-DCMAKE_C_COMPILER=" + a.cc, "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
               "-DCMAKE_C_FLAGS=" + " ".join([f for f in cflags if not f.startswith("-O")] + defines + ext.get("cflags", []))]
        if a.platform in KEY_ALIAS:
            cmd += ["-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=aarch64",
                    "-DCMAKE_ASM_COMPILER=" + a.cc, "-DCMAKE_CROSSCOMPILING_EMULATOR=qemu-aarch64"]
        with open(os.path.join(out, "cmake.log"), "w") as log:
            r = subprocess.run(cmd + args, stdout=log, stderr=subprocess.STDOUT)
            if r.returncode == 0:
                r = subprocess.run(["cmake", "--build", bdir, "-j2", "--target"] + targets,
                                   stdout=log, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            sys.exit("team cmake build failed; see " + os.path.join(out, "cmake.log"))
        cc_json = os.path.join(bdir, "compile_commands.json")
        if os.path.exists(cc_json):
            shutil.copy2(cc_json, os.path.join(out, "compile_commands.json"))
        for k, arc in enumerate(ext["archives"]):
            objs += unpack(os.path.join(bdir, expand(arc, env)), out, k, excl, tp)
    else:
        sys.exit("unknown external_build kind " + ext["kind"])
    if not objs:
        sys.exit("external build produced no objects")
    return objs


def unpack(archive, out, k, excl, tp):
    if not os.path.exists(archive):
        sys.exit("archive not found: " + archive)
    d = os.path.join(out, "obj", "ext%02d" % k)
    os.makedirs(d, exist_ok=True)
    names = subprocess.run([tp + "ar", "t", archive], capture_output=True, text=True).stdout.split()
    subprocess.run([tp + "ar", "x", os.path.abspath(archive)], cwd=d, check=True)
    return [os.path.join(d, n) for n in names
            if not any(fnmatch.fnmatch(n, x) for x in excl)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe")
    ap.add_argument("--platform", default="pi5", choices=sorted(PLATFORM_FLAGS))
    ap.add_argument("--cc", default=None)
    ap.add_argument("--set", action="append", default=[],
                    help="override a recipe variable, VAR=value")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    recipes = load_recipes()
    if a.list:
        for k in sorted(recipes):
            r = recipes[k]
            print("%-34s %-8s %s" % (k, r.get("variant", ""), r.get("note", "")))
        return
    if not a.recipe or a.recipe not in recipes:
        sys.exit("unknown recipe; use --list")
    rec = recipes[a.recipe]

    env = dict(rec.get("vars", {}))
    env.update(source_roots())
    env["HARNESS"] = HARNESS
    env["TOP"] = TOP
    env["PLATFORM"] = a.platform
    env["PLATFORM_KEY"] = KEY_ALIAS.get(a.platform, a.platform)
    if a.cc is None:
        a.cc = PLATFORM_CC.get(a.platform, os.environ.get("CC", "gcc"))
    tp = PLATFORM_TOOL_PREFIX.get(a.platform, "")
    plink = PLATFORM_LINK.get(a.platform, [])
    for kv in a.set:
        k, _, v = kv.partition("=")
        env[k] = v
    for k in list(env):
        env[k] = expand(env[k], env)

    out = os.path.join(TOP, "build", a.platform, a.recipe)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "obj"))

    if rec.get("tree"):
        srcs, incs = stage_tree(rec, env, out)
    else:
        srcs, incs = stage_sources(rec, env, out)
    apply_patches(rec, env, out)
    cflags = list(PLATFORM_FLAGS[a.platform])
    cflags += rec.get("cflags", [])
    cflags += rec.get("cflags_" + env["PLATFORM_KEY"], [])
    all_defines = rec.get("defines", []) + rec.get("defines_" + env["PLATFORM_KEY"], [])
    defines = ["-D" + d for d in all_defines]
    inc_flags = ["-I" + d for d in incs]
    inc_flags += ["-I" + d for d in PLATFORM_INC.get(a.platform, [])]
    if rec.get("use_common", False):
        inc_flags.append("-I" + os.path.join(HARNESS, "common"))
    inc_flags += ["-I" + os.path.join(HARNESS, "include"),
                  "-I" + os.path.join(HARNESS, "src")]

    # Harness crypto: the NIST DRBG always, mupq common when asked.
    harness_srcs = [os.path.join(HARNESS, "src", "nist_rng.c"),
                    os.path.join(HARNESS, "src", "pqclean_randombytes.c")]
    if rec.get("use_common", False):
        for c in rec.get("common_sources", ["fips202.c", "keccakf1600.c"]):
            harness_srcs.append(os.path.join(HARNESS, "common", c))

    if a.platform in CROSS:
        man = {"recipe": a.recipe, "platform": a.platform,
               "scheme": rec["scheme"], "param": rec["param"], "variant": rec["variant"],
               "sources": srcs, "harness_sources": harness_srcs,
               "include_dirs": [f[2:] for f in inc_flags],
               "defines": all_defines,
               "bench_defines": rec.get("bench_defines", []),
               "cflags": cflags, "libs": rec.get("libs", [])}
        if any(l == "-lcrypto" for l in man["libs"]):
            sys.exit("recipe needs OpenSSL; use its -portable variant on " + a.platform)
        with open(os.path.join(out, "manifest.json"), "w") as f:
            json.dump(man, f, indent=2)
        print("staged", out)
        return

    # 1. Scheme objects -> libscheme.a
    objs = []
    if rec.get("external_build"):
        objs = external_build(rec["external_build"], env, out, a, cflags, defines, tp)
        srcs = []
    for i, s in enumerate(srcs):
        o = os.path.join(out, "obj", "%03d_%s.o" % (i, os.path.basename(s)[:-2]))
        # -g adds debug sections only (code and size(1) figures unchanged)
        # so memcheck reports name source lines.
        sh([a.cc] + cflags + ["-g"] + defines + inc_flags + ["-c", s, "-o", o])
        objs.append(o)
    lib = os.path.join(out, "libscheme.a")
    sh([tp + "ar", "rcs", lib] + objs)
    with open(os.path.join(out, "size.txt"), "w") as f:
        subprocess.run([tp + "size", "-t"] + objs, stdout=f)

    # 2. Harness objects
    hobjs = []
    for s in harness_srcs:
        o = os.path.join(out, "obj", "h_" + os.path.basename(s)[:-2] + ".o")
        sh([a.cc] + cflags + defines + inc_flags + ["-c", s, "-o", o])
        hobjs.append(o)

    flag_str = " ".join(cflags + defines).replace(",", ";")
    ident = [
        '-DHARNESS_SCHEME="%s"' % rec["scheme"],
        '-DHARNESS_PARAM="%s"' % rec["param"],
        '-DHARNESS_VARIANT="%s"' % rec["variant"],
        '-DHARNESS_PLATFORM="%s"' % a.platform,
        '-DHARNESS_CFLAGS="%s"' % flag_str,
    ]
    libs = rec.get("libs", [])

    # 3. bench
    bench_srcs = [os.path.join(HARNESS, "src", "bench_main.c"),
                  os.path.join(HARNESS, "src", "hsha256.c"),
                  os.path.join(HARNESS, "platform", "plat_linux.c")]
    bench_defs = ["-D" + d for d in rec.get("bench_defines", [])]
    sh([a.cc] + cflags + defines + bench_defs + ident + inc_flags + bench_srcs +
       [lib] + hobjs + ["-o", os.path.join(out, "bench"), "-lpthread"] + libs + plink)

    # 4. genkat from the package's own generator
    if rec.get("genkat"):
        gk = expand(rec["genkat"], env)
        sh([a.cc] + cflags + defines + bench_defs + inc_flags + [gk, lib] + hobjs +
           ["-o", os.path.join(out, "genkat")] + libs + plink)

    # 4b. the package's own self-test, for packages whose known answers
    #     live in a test program rather than in a .rsp file (c-fn-dsa).
    #     It is built from the same staged sources and flags as bench.
    if rec.get("upstream_test"):
        ut = expand(rec["upstream_test"], env)
        sh([a.cc] + cflags + defines + inc_flags + [ut, lib] + hobjs +
           ["-o", os.path.join(out, "upstream_test"), "-lm"] + libs + plink)

    # 5. constant-time tests (ct/): Welch t-test always, memcheck when
    #    the Valgrind client header is installed.
    ct_dir = os.path.join(TOP, "ct")
    sh_soft([a.cc] + cflags + defines + bench_defs + ident + inc_flags +
       [os.path.join(ct_dir, "fixvsrand_sign.c"), "-DHARNESS_NO_MAIN",
        os.path.join(HARNESS, "platform", "plat_linux.c"), lib] + hobjs +
       ["-o", os.path.join(out, "ct_fixvsrand"), "-lm", "-lpthread"] + libs + plink, "ct_fixvsrand")
    if a.platform not in KEY_ALIAS and os.path.exists("/usr/include/valgrind/memcheck.h"):
        # Valgrind 3.22 decodes AVX2 but not AVX-512: the memcheck binary is
        # built for x86-64-v3 instead of znver5. The scheme library is
        # rebuilt with the same flags (in obj_vg/), so no AVX-512 code from
        # libscheme.a reaches Valgrind. Variants whose own flags ask for
        # AVX-512, GFNI or VAES still cannot be checked (run_ct.sh says so).
        vflags = [("-march=x86-64-v3" if f.startswith("-march=znver") else f) for f in cflags]
        vlib = lib
        vh = hobjs
        try:
            vlib, vh = memcheck_lib(a, vflags, cflags, srcs, harness_srcs, defines, inc_flags, out, tp, lib, hobjs,
                                    rec, env)
        except SystemExit:
            print("NOTE: x86-64-v3 objects for ct_memcheck did not build; using the main library", flush=True)
            vflags, vlib, vh = cflags, lib, hobjs
        sh_soft([a.cc] + vflags + ["-g"] + defines + bench_defs + inc_flags +
           [os.path.join(ct_dir, "memcheck_sign.c"), vlib] + vh +
           ["-o", os.path.join(out, "ct_memcheck")] + libs + plink, "ct_memcheck")

    # 6. CPU batch verification (RQ4 reference for the GPU)
    build_batch(a, cflags, defines, bench_defs, ident, inc_flags, harness_srcs, out, lib, hobjs, libs, plink)

    ver = subprocess.run([a.cc, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    with open(os.path.join(out, "build.json"), "w") as f:
        json.dump({"recipe": a.recipe, "platform": a.platform, "compiler": ver,
                   "cflags": cflags, "defines": all_defines,
                   "bench_defines": rec.get("bench_defines", []),
                   "includes": [f[2:] for f in inc_flags],
                   "sources": srcs, "harness_sources": harness_srcs,
                   "vars": env}, f, indent=2)
    print("built", out)


if __name__ == "__main__":
    main()
