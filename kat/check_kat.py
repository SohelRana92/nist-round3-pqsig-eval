#!/usr/bin/env python3
"""check_kat.py - compare harness KAT lines with an official .rsp file.

The harness prints, for each KAT count c:
  KAT,scheme,param,variant,platform,c,sha256(pk),sha256(sk),smlen,sha256(sm),open_ok
This script parses the .rsp file, hashes pk, sk and sm for the same
counts, and reports every mismatch.

Usage:
  bench kat 10 > kat_out.csv
  kat/check_kat.py PQCsignKAT_xxx.rsp kat_out.csv
Exit code 0 means every printed count matches and every open succeeded.
"""
import hashlib
import sys


def parse_rsp(path):
    vecs = {}
    cur = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k == "count":
                cur = int(v)
                vecs[cur] = {}
            elif cur is not None:
                vecs[cur][k] = v
    return vecs


def h(hexstr):
    return hashlib.sha256(bytes.fromhex(hexstr)).hexdigest()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    vecs = parse_rsp(sys.argv[1])
    seen = 0
    bad = 0
    with open(sys.argv[2]) as f:
        for line in f:
            p = line.strip().split(",")
            if not p or p[0] != "KAT":
                continue
            c = int(p[5])
            pk_h, sk_h, smlen, sm_h, ok = p[6], p[7], int(p[8]), p[9], p[10]
            if c not in vecs:
                print("count %d: not in .rsp" % c)
                bad += 1
                continue
            v = vecs[c]
            errs = []
            if h(v["pk"]) != pk_h:
                errs.append("pk")
            if h(v["sk"]) != sk_h:
                errs.append("sk")
            if int(v["smlen"]) != smlen:
                errs.append("smlen")
            if h(v["sm"]) != sm_h:
                errs.append("sm")
            if ok != "1":
                errs.append("open")
            seen += 1
            if errs:
                bad += 1
                print("count %d: MISMATCH in %s" % (c, ", ".join(errs)))
    print("checked %d KAT vectors, %d failed" % (seen, bad))
    sys.exit(1 if bad or seen == 0 else 0)


if __name__ == "__main__":
    main()
