#!/usr/bin/env python3
"""gen_opt_recipes.py - add the submitters' optimised builds to
registry/recipes.json (idempotent: existing opt-* entries are replaced).

Each optimised recipe reuses the KAT reference of the matching reference
recipe, because every team states that its optimised code produces the
same keys and signatures. A KAT pass therefore proves that the harness
drives the optimised code correctly.

Variant names
  opt-avx2     x86-64 AVX2 path (plus AES-NI/PCLMUL where the team uses them)
  opt-avx512   x86-64 AVX-512 path (MQOM: AVX-512 fields, VAES, Keccak times8)
  opt-gfni     x86-64 GFNI path (UOV, MAYO)
  opt-broadwell SQIsign x86-64 assembly field arithmetic
  opt-neon     AArch64 NEON path (+ ARMv8 AES where the team uses it)
  opt-arm64    SQIsign AArch64 assembly field arithmetic

"platforms" lists where the recipe is meant to run; tools/kat_all.py
skips a recipe on any other platform. x86-generic (this build server,
no GFNI or VAES) only runs the AVX2 recipes.
"""
import copy
import json
import os

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(TOP, "registry", "recipes.json")
X86 = ["x86", "x86-generic"]
ZEN5 = ["x86"]
ARM = ["pi5", "pi5-qemu"]


def uov_kat(p):
    """pqov's SHA256SUMS lists the SHA-256 of the 100-vector .rsp per
    parameter set: '<hash> <PARAM> <VARIANT> KAT/<name>'."""
    name = p.replace("_pkc_skc", "-pkc-skc").replace("_pkc", "-pkc")
    return {"method": "sha256", "list": "${SRC}/pqov/SHA256SUMS", "key": "KAT/%s\n" % name}


def main():
    doc = json.load(open(REG))
    r = doc["recipes"]
    for k in [k for k in r if "-opt-" in k and r[k].get("generated_by") == "gen_opt_recipes.py"]:
        del r[k]
    new = {}

    # UOV ref-nist: check against pqov SHA256SUMS instead of the earlier
    # self-generated note (the team publishes the digest of each .rsp).
    for k, v in r.items():
        if v["scheme"] == "UOV" and v["variant"] == "ref-nist":
            v["kat"] = uov_kat(v["param"])
            if "_NIST_KAT_" not in v.get("defines", []):
                v["defines"] = v.get("defines", []) + ["_NIST_KAT_"]

    # ---------------- UOV: NIST Optimized_Implementation folders ----------
    uov_opt = "${NIST}/uov/Optimized_Implementation"
    for k, v in list(r.items()):
        if v["scheme"] != "UOV" or v["variant"] != "ref-nist":
            continue
        p = v["param"]
        for var, sub, fl, plats in (("opt-avx2", "avx2", ["-mavx2", "-maes"], X86),
                                    ("opt-gfni", "gfni", ["-mavx2", "-mgfni", "-maes"], ZEN5),
                                    ("opt-neon", "neon", ["-flax-vector-conversions"], ARM)):
            new["uov-%s-%s" % (p, var)] = {
                "scheme": "UOV", "param": p, "variant": var, "platforms": plats,
                "note": "pqov Optimized_Implementation/%s (team config.h); OpenSSL for SHAKE" % sub,
                "vars": {"ROOT": uov_opt + "/" + sub},
                "source_dirs": ["${ROOT}/" + p], "include_dirs": ["${ROOT}/nistkat"],
                "drop": ["rng.c", "PQCgenKAT_sign.c"],
                # _NIST_KAT_ routes the package's randombytes() to rng.h (the
                # harness DRBG); without it the optimised folders call
                # OpenSSL RAND_bytes under a namespaced name.
                "defines": ["_NIST_KAT_"],
                "cflags": ["-std=c99"] + fl, "libs": ["-lcrypto"],
                "genkat": "${ROOT}/nistkat/PQCgenKAT_sign.c",
                "kat": uov_kat(p)}

    # ---------------- MAYO: same sources, team's platform headers ---------
    for k, v in list(r.items()):
        if v["scheme"] != "MAYO" or v["variant"] != "ref":
            continue
        p = v["param"]
        base_defs = [d for d in v["defines"] if d != "MAYO_BUILD_TYPE_REF"]
        for var, bt, defs, incs, fl, drop, plats in (
            ("opt-avx2", "AVX2", ["MAYO_AVX", "ENABLE_AESNI"], ["AVX2", "generic"], ["-mavx2", "-maes"],
             ["aes_neon.c"], X86),
            ("opt-gfni", "GFNI", ["MAYO_AVX", "MAYO_GFNI", "ENABLE_AESNI"], ["AVX2", "generic"],
             ["-mavx2", "-maes", "-mgfni", "-mavx512f", "-mavx512bw", "-mavx512vl"], ["aes_neon.c"], ZEN5),
            ("opt-neon", "NEON", ["MAYO_NEON", "ENABLE_AESNEON"], ["neon", "generic"], [], [], ARM)):
            n = copy.deepcopy(v)
            n.update({"variant": var, "platforms": plats,
                      "note": "MAYO-C %s build (src/%s headers)" % (bt.lower(), incs[0]),
                      "include_dirs": ["${ROOT}/include"] + ["${ROOT}/src/" + i for i in incs],
                      "drop": ["randombytes_system.c", "randombytes_ctrdrbg.c"] + drop,
                      "defines": ["MAYO_BUILD_TYPE_" + bt] + defs + base_defs,
                      "cflags": ["-std=c99"] + fl})
            new["mayo-%s-%s" % (p, var)] = n

    # ---------------- SNOVA: dist/avx2 -------------------------------------
    for k, v in list(r.items()):
        if v["scheme"] != "SNOVA" or v["variant"] != "ref":
            continue
        p = v["param"]
        n = copy.deepcopy(v)
        n.update({"variant": "opt-avx2", "platforms": X86,
                  "note": "SNOVA dist/avx2 from makesnova.py (SNOVA_OPT=20 as in the team Makefile)",
                  "vars": {"ROOT": "${SRC}/SNOVA/dist/avx2/" + p},
                  "only_sources": ["snova_avx2_16.c", "symmetric.c", "sign.c", "aes.c"],
                  "defines": ["SNOVA_OPT=20"], "cflags": ["-std=c11", "-mavx2"]})
        new["snova-%s-opt-avx2" % p] = n

    # ---------------- MQOM: team Makefile ----------------------------------
    for k, v in list(r.items()):
        if v["scheme"] != "MQOM" or v["variant"] != "ref":
            continue
        p = v["param"]
        pdefs = [d for d in v["defines"] if d.startswith("MQOM3_PARAM_")] + ["NDEBUG"]
        for var, args, kdir, plats, fl in (
            ("opt-avx2", ["KECCAK_PLATFORM=avx2", "FIELDS_AVX2=1", "RIJNDAEL_AES_NI=1"], "avx2", X86,
             ["-mavx2", "-maes", "-mpclmul"]),
            ("opt-avx512", ["KECCAK_PLATFORM=avx512", "FIELDS_AVX512=1", "RIJNDAEL_VAES=1"], "avx512", ZEN5,
             ["-mavx2", "-maes", "-mpclmul", "-mavx512f", "-mavx512bw", "-mavx512vl", "-mvaes",
              "-mvpclmulqdq", "-mgfni"]),
            ("opt-neon", ["KECCAK_PLATFORM=aarch64", "FIELDS_NEON=1", "RIJNDAEL_ARM_AES=1"], "aarch64", ARM, [])):
            new["mqom-%s-%s" % (p, var)] = {
                "scheme": "MQOM", "param": p, "variant": var, "platforms": plats,
                "note": "MQOM v3 built by the team Makefile with " + " ".join(args),
                "vars": {"ROOT": "${SRC}/mqom-v3"}, "tree": "${ROOT}", "source_dirs": [],
                "include_dirs": [".", "fields", "fields_bitsliced", "generator", "sha3", "sha3/" + kdir],
                "drop": [],
                "external_build": {"kind": "make", "args": args, "targets": ["all"],
                                   "archives": ["sha3/libhash.a"]},
                "defines": pdefs, "cflags": ["-std=gnu11"] + fl,
                "genkat": "${ROOT}/generator/PQCgenKAT_sign.c",
                "kat": copy.deepcopy(v["kat"])}

    # ---------------- FAEST: team's CPU feature switches -------------------
    for k, v in list(r.items()):
        if v["scheme"] != "FAEST" or v["variant"] != "ref":
            continue
        p = v["param"]
        for var, defs, fl, plats in (
            ("opt-avx2", ["HAVE_SSE2", "HAVE_AVX2", "HAVE_AESNI", "HAVE_PCLMUL", "HAVE_MM_LOADU_SI64",
                          "HAVE_ATTR_VECTOR_SIZE"], ["-msse2", "-mavx2", "-maes", "-mpclmul"], X86),
            ("opt-neon", ["HAVE_NEON", "HAVE_ARM_AES", "HAVE_ATTR_VECTOR_SIZE"], [], ARM)):
            n = copy.deepcopy(v)
            n.update({"variant": var, "platforms": plats,
                      "note": "faest-ref with the feature macros its meson build sets on this CPU",
                      "defines": v["defines"] + defs, "cflags": v["cflags"] + fl})
            new["faest-%s-%s" % (p, var)] = n

    # ---------------- SDitH: NIST Optimized_Implementation -----------------
    for k, v in list(r.items()):
        if v["scheme"] != "SDitH" or v["variant"] != "ref":
            continue
        p = v["param"]
        n = copy.deepcopy(v)
        root = "${NIST}/sdith/Optimized_Implementation/" + p
        n.update({"variant": "opt-avx2", "platforms": X86,
                  "note": "SDitH Optimized_Implementation: AVX2/AES-NI/PCLMUL backend, AVX2 Keccak",
                  "vars": {"ROOT": root}, "tree": "${ROOT}",
                  "source_dirs": ["src", "lib/aes", "lib/sha3", "generator"],
                  "defines": ["NDEBUG"],
                  "cflags": ["-std=gnu11", "-msse2", "-mavx2", "-maes", "-mpclmul"]})
        for key in [x for x in n if x.startswith("source_dirs_")]:
            del n[key]
        n["asm_sources"] = True
        n["source_dirs_x86"] = ["lib/sha3/avx2"]
        n["source_dirs_x86-generic"] = ["lib/sha3/avx2"]
        new["sdith-%s-opt-avx2" % p] = n

    # ---------------- QR-UOV: src/avx2 -------------------------------------
    for k, v in list(r.items()):
        if v["scheme"] != "QR-UOV" or v["variant"] != "ref-nist":
            continue
        p = v["param"]
        n = copy.deepcopy(v)
        n.update({"variant": "opt-avx2", "platforms": X86,
                  "note": "QR-UOV src/avx2 (team GNUmakefile IMPL=avx2 flags); OpenSSL for SHAKE",
                  "source_dirs": ["${ROOT}/src", "${ROOT}/src/avx2"],
                  "only_sources": ["sign.c", "qruov_common.c", "qrop.c", "prg.c", "prim.c", "linsys.c",
                                   "qruov.c", "emi_transform.c", "emi_matrix.c", "emi_transform_gen.c",
                                   "helpers.c", "kernel.c", "x86aesni.c"],
                  "defines": v["defines"] + ["PRIM_AES_BACKEND_X86AESNI=1"],
                  "cflags": ["-std=gnu11", "-mavx2", "-mbmi2", "-maes"]})
        new["qruov-%s-opt-avx2" % p] = n

    # ---------------- SQIsign: team CMake ----------------------------------
    for k, v in list(r.items()):
        if v["scheme"] != "SQIsign" or v["variant"] != "ref-portable":
            continue
        p = v["param"]
        for var, bt, plats in (("opt-broadwell", "broadwell", X86), ("opt-arm64", "arm64", ARM)):
            arcs = ["src/libsqisign_%s_test_nistapi.a" % p, "src/libsqisign_%s_test.a" % p]
            arcs += ["src/%s/ref/%s/libsqisign_%s_%s.a" % (m, p, m, p)
                     for m in ("signature", "verification", "id2iso", "quaternion", "hd", "ec")]
            arcs += ["src/gf/%s/%s/libsqisign_gf_%s.a" % (bt, p, p),
                     "src/mp/ref/%s/libsqisign_mp_%s.a" % (p, p),
                     "src/precomp/ref/%s/libsqisign_precomp_%s.a" % (p, p),
                     "src/common/generic/libsqisign_common_test.a"]
            new["sqisign-%s-%s" % (p, var)] = {
                "scheme": "SQIsign", "param": p, "variant": var, "platforms": plats,
                "note": "the-sqisign CMake SQISIGN_BUILD_TYPE=%s (team flags: -O2, LTO)" % bt,
                "vars": {"ROOT": "${SRC}/the-sqisign"}, "tree": "${ROOT}", "source_dirs": [],
                "include_dirs": ["include", "src/nistapi/" + p], "drop": ["build"],
                "external_build": {"kind": "cmake",
                                   "args": ["-DSQISIGN_BUILD_TYPE=" + bt, "-DENABLE_TESTS=OFF",
                                            "-DENABLE_STRICT=OFF"],
                                   "targets": ["PQCgenKAT_sign_" + p],
                                   "archives": arcs, "exclude": ["randombytes_*"]},
                "defines": [], "cflags": [], "libs": ["-lm"],
                # the api.h namespace macros need these in the driver only
                "bench_defines": ["ENABLE_SIGN", "SQISIGN_VARIANT=" + p,
                                  "SQISIGN_BUILD_TYPE_" + bt.upper()],
                "kat": copy.deepcopy(v["kat"]), "lto": True}

    for n in new.values():
        n["generated_by"] = "gen_opt_recipes.py"
    r.update(new)
    doc["recipes"] = dict(sorted(r.items()))
    tmp = REG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, REG)
    print("added %d optimised recipes; registry now holds %d" % (len(new), len(r)))


if __name__ == "__main__":
    main()
