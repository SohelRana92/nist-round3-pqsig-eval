#!/usr/bin/env python3
"""Verify ecdsa_dump output with python-cryptography (OpenSSL backend)."""
import sys
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes
bad = 0
for line in sys.stdin:
    pk, msg, sig = (line.split() + [""])[:3] if len(line.split()) == 3 else (line.split()[0], "", line.split()[1])
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex("04" + pk))
    r = int(sig[:64], 16); s = int(sig[64:], 16)
    try:
        pub.verify(utils.encode_dss_signature(r, s), bytes.fromhex(msg), ec.ECDSA(hashes.SHA256()))
        print("ECDSA P-256 signature on %r: verified by OpenSSL" % bytes.fromhex(msg))
    except Exception as ex:
        bad += 1
        print("FAIL", ex)
sys.exit(bad)
