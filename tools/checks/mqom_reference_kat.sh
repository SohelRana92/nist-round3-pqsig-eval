#!/bin/sh
# mqom_reference_kat.sh VARIANT OUTDIR
# Builds MQOM's own KAT generator with the team's Makefile (OpenSSL rng.c,
# auto-selected AES backend) and writes its .rsp into OUTDIR/VARIANT/.
# The harness portable build must reproduce this file exactly.
set -eu
V=$1; OUT=$2; SRC=${MQOM_SRC:-${PQSIG_SOURCES:-$HOME/pqsig-src}/src/mqom-v3}
T=$(mktemp -d); cp -r "$SRC"/. "$T"; cd "$T"
eval "$(python3 manage.py env "$V" | sed 's/^export //')"
make -s kat_gen EXTRA_CFLAGS="$EXTRA_CFLAGS" KECCAK_PLATFORM=opt64 >/dev/null 2>&1
mkdir -p "$OUT/$V"; cd "$OUT/$V"; "$T/kat_gen" >/dev/null; rm -rf "$T"
