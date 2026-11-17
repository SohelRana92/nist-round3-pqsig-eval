#!/usr/bin/env python3
"""message_cost.py - message-size cost (RQ5, the message-size table).

  python3 paper/scripts/message_cost.py

Input : paper/data/sizes_from_api.csv (pk and signature bytes)
Output: paper/data/message_cost.csv and paper/tables/tab_message.tex

Part 1, frames per signed 64-byte reading. The application payload is the
64-byte reading followed by the signature. Each link model below is fixed
by a standard; the comments name the clause each number comes from, and
the paper's table note repeats the assumptions.

  IEEE 802.15.4 + 6LoWPAN (RFC 4944), no header compression:
    127-byte PHY payload (aMaxPhyPacketSize, IEEE 802.15.4).
    MAC header 9 bytes (frame control 2, sequence 1, PAN ID 2 with PAN ID
    compression, short destination 2, short source 2) and FCS 2, so 116
    bytes of MAC payload per frame.
    IPv6 dispatch 1 byte + uncompressed IPv6 header 40 + UDP 8 (RFC 4944
    Sec. 5.1 IPv6 dispatch; RFC 8200; RFC 768).
    If the 6LoWPAN datagram does not fit one frame: FRAG1 header 4 bytes,
    FRAGN header 5 bytes, fragment payload a multiple of 8 bytes except in
    the last fragment (RFC 4944 Sec. 5.3).
  Bluetooth LE, L2CAP LE credit-based channel:
    251-byte maximum LL data payload (Data Length Extension).
    Every K-frame carries a 4-byte basic L2CAP header; the first K-frame of
    an SDU also carries the 2-byte SDU length. One K-frame per LL PDU, so
    247 bytes of SDU per PDU, 245 in the first.
  IPv6 over a 1,280-byte path MTU (RFC 8200 minimum):
    IPv6 header 40, UDP header 8. A UDP datagram larger than 1,232 bytes
    is split with the 8-byte Fragment header; every fragment but the last
    carries a multiple of 8 bytes, at most 1,280-40-8 = 1,232.

Part 2, certificate chain bytes. A root, an intermediate and a leaf
certificate, each holding one public key of the scheme and signed with
the scheme. The X.509 structure without key and signature is measured
from a real three-certificate Ed25519 chain made by OpenSSL on this
machine (Ed25519 and ECDSA P-256 rows are measured chains). Key and signature are then swapped in and every DER length field
that changes is recomputed. Algorithm identifiers keep the length of an
OID in the NIST arc (2.16.840.1.101.3.4.3.x, 11 bytes encoded, as used
for ML-DSA); the Ed25519 OID is 5 bytes, so each identifier grows by 6.
"""
import csv
import math
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
READING = 64


def frames_154(payload):
    """(frames, bytes on air above the PHY) for one 6LoWPAN datagram."""
    mac_payload = 127 - 9 - 2
    dgram = 1 + 40 + 8 + payload
    if dgram <= mac_payload:
        return 1, dgram + 11
    first = (mac_payload - 4) // 8 * 8
    rest = (mac_payload - 5) // 8 * 8
    n = 1 + math.ceil((dgram - first) / rest)
    return n, dgram + 11 * n + 4 + 5 * (n - 1)


def frames_ble(payload):
    """(LL PDUs, L2CAP bytes) for one SDU on an LE credit-based channel."""
    if payload <= 245:
        return 1, payload + 6
    n = 1 + math.ceil((payload - 245) / 247)
    return n, payload + 2 + 4 * n


def frames_ipv6(payload):
    """(packets, IP-layer bytes) for one UDP datagram over a 1,280-byte MTU."""
    udp = 8 + payload
    if udp <= 1232:
        return 1, 40 + udp
    n = math.ceil(udp / 1232)
    return n, udp + n * (40 + 8)


def der_len(n):
    if n < 128:
        return 1
    if n < 256:
        return 2
    if n < 65536:
        return 3
    return 4


def tlv(n):
    return 1 + der_len(n) + n


def openssl_chain(alg):
    """Make a root, an intermediate and a leaf certificate with OpenSSL and
    return the DER size of each. alg is "ed25519" or "p256". The root and
    the intermediate carry basicConstraints CA:TRUE and keyUsage
    keyCertSign; the leaf carries keyUsage digitalSignature. Subject and
    authority key identifiers are added as OpenSSL does by default."""
    d = tempfile.mkdtemp(prefix="chain_")

    def run(*a):
        subprocess.run(a, cwd=d, check=True, capture_output=True)
    gen = (["-algorithm", "ed25519"] if alg == "ed25519"
           else ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"])
    md = [] if alg == "ed25519" else ["-sha256"]
    with open(os.path.join(d, "ca.ext"), "w") as f:
        f.write("basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
                "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n")
    with open(os.path.join(d, "leaf.ext"), "w") as f:
        f.write("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n")
    for k in ("root", "int", "leaf"):
        run("openssl", "genpkey", *gen, "-out", k + ".key")
    run("openssl", "req", "-new", "-x509", *md, "-key", "root.key", "-subj", "/CN=Root CA", "-days", "3650",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-out", "root.pem")
    run("openssl", "req", "-new", "-key", "int.key", "-subj", "/CN=Intermediate CA", "-out", "int.csr")
    run("openssl", "x509", "-req", *md, "-in", "int.csr", "-CA", "root.pem", "-CAkey", "root.key",
        "-days", "1825", "-set_serial", "2", "-extfile", "ca.ext", "-out", "int.pem")
    run("openssl", "req", "-new", "-key", "leaf.key", "-subj", "/CN=sensor-0001", "-out", "leaf.csr")
    run("openssl", "x509", "-req", *md, "-in", "leaf.csr", "-CA", "int.pem", "-CAkey", "int.key",
        "-days", "365", "-set_serial", "3", "-extfile", "leaf.ext", "-out", "leaf.pem")
    sizes = []
    for k in ("root", "int", "leaf"):
        run("openssl", "x509", "-in", k + ".pem", "-outform", "DER", "-out", k + ".der")
        sizes.append(os.path.getsize(os.path.join(d, k + ".der")))
    run("openssl", "verify", "-CAfile", "root.pem", "-untrusted", "int.pem", "leaf.pem")
    return sizes


def model_cert(ed_size, pk, sig, oid_growth=6):
    """Rebuild one certificate's DER size with a pk-byte key and a sig-byte
    signature, starting from an Ed25519 certificate of ed_size bytes."""
    ED_PK, ED_SIG = 32, 64
    # Ed25519 pieces (RFC 8410): SPKI = SEQ{ AlgId(7) , BIT STRING(1+32) }
    spki_ed = tlv(7 + tlv(1 + ED_PK))
    sig_ed = tlv(1 + ED_SIG)
    cert_content_ed = None
    # find the content length c with 1 + der_len(c) + c == ed_size
    for c in range(ed_size - 5, ed_size):
        if 1 + der_len(c) + c == ed_size:
            cert_content_ed = c
            break
    algid_outer = 7
    tbs_ed = cert_content_ed - algid_outer - sig_ed
    for c in range(tbs_ed - 5, tbs_ed):
        if 1 + der_len(c) + c == tbs_ed:
            tbs_content_ed = c
            break
    tbs_other = tbs_content_ed - spki_ed           # everything in TBS but the SPKI
    # new pieces; the TBS signature AlgId and the SPKI AlgId grow by oid_growth each
    spki = tlv(7 + oid_growth + tlv(1 + pk))
    tbs = tlv(tbs_other + oid_growth + spki)
    cert = tlv(tbs + algid_outer + oid_growth + tlv(1 + sig))
    return cert


def main():
    sizes = list(csv.DictReader(open(os.path.join(ROOT, "paper", "data", "sizes_from_api.csv"))))
    ed = openssl_chain("ed25519")
    ec = openssl_chain("p256")
    rows = []
    for r in sizes:
        pk, sig = int(r["pk_bytes"]), int(r["sig_bytes"])
        p = READING + sig
        f1, b1 = frames_154(p)
        f2, b2 = frames_ble(p)
        f3, b3 = frames_ipv6(p)
        if r["scheme"] == "Ed25519":
            chain = sum(ed)
            how = "measured"
        elif r["scheme"] == "ECDSA":
            chain = sum(ec)
            how = "measured"
        else:
            chain = sum(model_cert(e, pk, sig) for e in ed)
            how = "modelled"
        rows.append([r["scheme"], r["param"], pk, sig, f1, b1, f2, b2, f3, b3, chain, how])
    out = os.path.join(ROOT, "paper", "data", "message_cost.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "param", "pk", "sig", "frames_154", "bytes_154", "frames_ble", "bytes_ble",
                    "frames_ipv6", "bytes_ipv6", "chain_bytes", "chain_method"])
        w.writerows(rows)
    print("Ed25519 chain measured (root, int, leaf):", ed)
    print("ECDSA P-256 chain measured (root, int, leaf):", ec)
    print("wrote", out)


if __name__ == "__main__":
    main()
