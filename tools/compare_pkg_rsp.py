#!/usr/bin/env python3
"""Compare the KAT files of the official NIST zips with the KAT files we validated against.

Usage:  python3 tools/compare_pkg_rsp.py ~/pqc-pkgs ~/pqsig-src

Every recipe on the x86 PC passed its KAT against the team's own .rsp files (or
digest lists) in the source tree. This script checks that those files are the
same as the ones in the official zips:
  identical   the .rsp file in the zip is byte-identical to one in the source tree
  same_vec0   not byte-identical (for example a different number of vectors), but
              vector 0 (pk, sk, sm) is equal to vector 0 of a source-tree file
  digest_ok   the .rsp file's SHA-256 or SHAKE256-24 digest is in a digest list of the
              source tree (the list our 100-vector KAT runs were checked against), or
              every digest line of a digest file in the zip appears in the source tree
  differs     none of the above
Writes results/package_rsp_compare.csv and prints one summary line per zip.
"""
import csv, glob, hashlib, os, re, sys, tempfile, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEX64 = re.compile(r"\b(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{48})\b")
DIGEST_NAME = re.compile(r"(sha256|sha3|shake|sums|digest|kat).*\.(txt|sha256|sum|md)$|SHA256SUMS|^KATs$", re.I)

def fsha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def shake24(p):
    h = hashlib.shake_256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest(24)

def vec0(p):
    with open(p, errors="replace") as f:
        txt = f.read(4 << 20)          # vector 0 sits at the top of the file
    m = re.search(r"count = 0\b(.*?)(?:\ncount = |\Z)", txt, re.S)
    if not m:
        return None
    out = []
    for name in ("pk", "sk", "sm"):
        f = re.search(r"\n%s = ([0-9A-Fa-f]*)" % name, m.group(1))
        if not f:
            return None
        out.append(hashlib.sha256(bytes.fromhex(f.group(1))).hexdigest())
    return tuple(out)

def scan(tree):
    files, v0s, digests = set(), set(), set()
    for p in glob.glob(os.path.join(tree, "**", "*"), recursive=True):
        if not os.path.isfile(p):
            continue
        b = os.path.basename(p)
        if b.endswith(".rsp"):
            files.add(fsha(p))
            v = vec0(p)
            if v:
                v0s.add(v)
        elif DIGEST_NAME.search(b) and os.path.getsize(p) < (1 << 20):
            digests.update(h.lower() for h in HEX64.findall(open(p, errors="replace").read()))
    return files, v0s, digests

def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pkgs, src = (os.path.expanduser(a) for a in sys.argv[1:])
    print("scanning source tree", src, "...", flush=True)
    sfiles, sv0, sdig = scan(src)
    print("  %d .rsp files, %d digest values\n" % (len(sfiles), len(sdig)), flush=True)
    out = os.path.join(ROOT, "results", "package_rsp_compare.csv")
    with open(out, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["zip", "file", "status"])
        for z in sorted(glob.glob(os.path.join(pkgs, "*.zip"))):
            cnt = {"identical": 0, "same_vec0": 0, "digest_ok": 0, "differs": 0}
            with tempfile.TemporaryDirectory() as tmp:
                zipfile.ZipFile(z).extractall(tmp)
                for inner in glob.glob(os.path.join(tmp, "**", "*.zip"), recursive=True):
                    try:
                        zipfile.ZipFile(inner).extractall(inner + "_x")
                    except zipfile.BadZipFile:
                        pass
                for p in sorted(glob.glob(os.path.join(tmp, "**", "*"), recursive=True)):
                    if not os.path.isfile(p):
                        continue
                    b, rel = os.path.basename(p), os.path.relpath(p, tmp)
                    if b.endswith(".rsp"):
                        fs = fsha(p)
                        if fs in sfiles:
                            st = "identical"
                        elif fs in sdig or shake24(p) in sdig:
                            st = "digest_ok"
                        elif vec0(p) in sv0:
                            st = "same_vec0"
                        else:
                            st = "differs"
                    elif DIGEST_NAME.search(b) and os.path.getsize(p) < (1 << 20):
                        hs = [h.lower() for h in HEX64.findall(open(p, errors="replace").read())]
                        if not hs:
                            continue
                        n_ok = sum(h in sdig for h in hs)
                        st = "digest_ok" if n_ok == len(hs) else "differs"
                        rel += " (%d/%d digests found)" % (n_ok, len(hs))
                    else:
                        continue
                    cnt[st] += 1
                    w.writerow([os.path.basename(z), rel, st])
            print("%-34s identical=%-3d same_vec0=%-3d digest_ok=%-3d differs=%d"
                  % (os.path.basename(z), cnt["identical"], cnt["same_vec0"],
                     cnt["digest_ok"], cnt["differs"]), flush=True)
    print("\nwrote", out)

if __name__ == "__main__":
    main()
