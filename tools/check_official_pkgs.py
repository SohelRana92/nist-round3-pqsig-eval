#!/usr/bin/env python3
"""Record the official NIST Round-3 zips and check them against our KAT runs.

Usage:  python3 tools/check_official_pkgs.py ~/pqc-pkgs

For every *.zip in the folder it writes one row to results/package_hashes.csv
(file, download date = file mtime, SHA-256). It then unpacks each zip into a
temporary folder, reads every .rsp KAT file, and checks whether vector count 0
(pk, sk, sm) appears in results/kat_reference/*.csv. A match means the official
package and the repository commit we measured produce the same keys and
signatures for that parameter set.
"""
import csv, datetime, glob, hashlib, os, re, sys, tempfile, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def load_reference():
    ref = {}
    for p in glob.glob(os.path.join(ROOT, "results", "kat_reference", "*.csv")):
        recipe = os.path.basename(p)[:-4]
        for row in csv.reader(open(p)):
            if row and row[0] == "KAT" and row[5] == "0":
                ref[(row[6], row[7], row[9])] = recipe
    return ref

def first_vector(rsp):
    txt = open(rsp, errors="replace").read()
    m = re.search(r"count = 0\b(.*?)(?:\ncount = |\Z)", txt, re.S)
    if not m:
        return None
    blk = m.group(1)
    def field(name):
        f = re.search(r"\n%s = ([0-9A-Fa-f]*)" % name, blk)
        return bytes.fromhex(f.group(1)) if f else None
    pk, sk, sm = field("pk"), field("sk"), field("sm")
    if pk is None or sk is None or sm is None:
        return None
    h = lambda b: hashlib.sha256(b).hexdigest()
    return h(pk), h(sk), h(sm)

def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = os.path.expanduser(sys.argv[1])
    zips = sorted(glob.glob(os.path.join(folder, "*.zip")))
    if not zips:
        sys.exit("no .zip files in %s" % folder)
    ref = load_reference()
    out = os.path.join(ROOT, "results", "package_hashes.csv")
    rep = os.path.join(ROOT, "results", "package_kat_match.csv")
    with open(out, "w", newline="") as fo, open(rep, "w", newline="") as fr:
        wo, wr = csv.writer(fo), csv.writer(fr)
        wo.writerow(["file", "download_date", "sha256"])
        wr.writerow(["zip", "rsp_file", "status", "our_recipe"])
        for z in zips:
            date = datetime.date.fromtimestamp(os.path.getmtime(z)).isoformat()
            wo.writerow([os.path.basename(z), date, sha256_file(z)])
            n_rsp = n_ok = 0
            with tempfile.TemporaryDirectory() as tmp:
                zipfile.ZipFile(z).extractall(tmp)
                # nested zips (for example a separate KAT archive) are unpacked once more
                for inner in glob.glob(os.path.join(tmp, "**", "*.zip"), recursive=True):
                    try:
                        zipfile.ZipFile(inner).extractall(inner + "_x")
                    except zipfile.BadZipFile:
                        pass
                for rsp in sorted(glob.glob(os.path.join(tmp, "**", "*.rsp"), recursive=True)):
                    n_rsp += 1
                    v = first_vector(rsp)
                    rel = os.path.relpath(rsp, tmp)
                    if v is None:
                        wr.writerow([os.path.basename(z), rel, "unreadable", ""])
                    elif v in ref:
                        n_ok += 1
                        wr.writerow([os.path.basename(z), rel, "match", ref[v]])
                    else:
                        wr.writerow([os.path.basename(z), rel, "no_match", ""])
            print("%-40s %s  rsp=%d  matched=%d" % (os.path.basename(z), date, n_rsp, n_ok))
    print("\nwrote", out)
    print("wrote", rep, "(no_match rows include Category 3 and 5 sets and variants we did not run)")

if __name__ == "__main__":
    main()
