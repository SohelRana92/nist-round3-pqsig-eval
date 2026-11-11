#!/usr/bin/env python3
"""shake_digest.py - print the 24-byte SHAKE256 digest of a file, in the
format of SNOVA's dist/KATs list, so a regenerated .rsp can be checked
against the team's published digest.
Usage: kat/shake_digest.py PQCsignKAT_xxx.rsp"""
import hashlib, sys
d = hashlib.shake_256(open(sys.argv[1], "rb").read()).hexdigest(24)
print(d)
