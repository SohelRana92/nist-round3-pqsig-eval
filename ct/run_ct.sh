#!/bin/sh
# run_ct.sh RECIPE PLATFORM [N_MEASUREMENTS]
# Runs the two constant-time tests that tools/hbuild.py builds next to
# bench, and appends their CT rows to results/ct_<platform>.csv.
#   PLATFORM: pi5 or x86.  Memcheck needs Valgrind:  sudo apt install valgrind
# Run with the board otherwise idle and the CPU governor set to performance.
set -eu
R=$1; P=$2; N=${3:-100000}
TOP=$(cd "$(dirname "$0")/.." && pwd)
B=$TOP/build/$P/$R
[ -x "$B/ct_fixvsrand" ] || python3 "$TOP/tools/hbuild.py" --recipe "$R" --platform "$P"
OUT=$TOP/results/ct_$P.csv
mkdir -p "$TOP/results"
[ -f "$OUT" ] || echo "tag,scheme,param,variant,platform,test,n,max_abs_t,result" > "$OUT"
# MEMCHECK_ONLY=1 skips the timing test (to redo memcheck alone).
if [ "${MEMCHECK_ONLY:-0}" != 1 ]; then
    ROW=$("$B/ct_fixvsrand" "$N" | grep '^CT,')
    echo "$ROW" >> "$OUT"
    echo "$ROW"
fi
if [ -x "$B/ct_memcheck" ] && command -v valgrind >/dev/null 2>&1; then
    set +e
    valgrind --error-exitcode=42 --track-origins=yes "$B/ct_memcheck" 2 > /dev/null 2> "$B/memcheck.log"
    RC=$?
    set -e
    # Exit 42 = memcheck reports. Any other failure is not a result about
    # the scheme: Valgrind 3.22 cannot decode AVX-512, GFNI or VAES code
    # and stops with SIGILL (exit 132).
    if [ $RC -eq 0 ]; then
        V=no_report
    elif [ $RC -eq 42 ]; then
        V=reports_$(sed -n 's/.*ERROR SUMMARY: [0-9]* errors from \([0-9]*\) contexts.*/\1/p' "$B/memcheck.log" | tail -1)_contexts
    elif grep -q "unhandled instruction" "$B/memcheck.log"; then
        V=not_run_valgrind_cannot_decode_isa
    else
        V=not_run_valgrind_exit_$RC
    fi
    S=$(python3 -c "import json;r=json.load(open('$TOP/registry/recipes.json'))['recipes']['$R'];print(r['scheme']+','+r['param']+','+r['variant'])")
    echo "CT,$S,$P,memcheck_sign,2,,$V" >> "$OUT"
    echo "CT,$S,$P,memcheck_sign,2,,$V"
    echo "memcheck log: $B/memcheck.log"
else
    echo "ct_memcheck not built or valgrind missing; memcheck skipped"
fi
