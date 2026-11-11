#!/bin/sh
# fetch_sources.sh - recreate the source tree the recipes expect.
#
#   sh tools/fetch_sources.sh                 # into ~/pqsig-src
#   PQSIG_SOURCES=/data/pqsig-src sh tools/fetch_sources.sh
#
# Creates
#   $PQSIG_SOURCES/src/<repo>   team repositories at the commits we validated
#   $PQSIG_SOURCES/nist/uov     pqov create_nist_project.py output
#   $PQSIG_SOURCES/nist/faest   faest-ref tools/prepare_nist.py output (with KAT/)
#   $PQSIG_SOURCES/nist/sdith   sdith utils/make_nist_package.py output (with KAT/)
#   $PQSIG_SOURCES/nist/mqom_ref/<set>/*.rsp   MQOM reference KATs from the team Makefile
# and runs the SNOVA and SQIsign source generators inside their repositories.
#
# Needs: git, python3, gcc, make, cmake, libssl-dev (MQOM's KAT generator
# links OpenSSL), meson and ninja (pip install meson ninja) for FAEST.
# Takes 10 to 30 minutes, most of it MQOM's 18 KAT builds.
set -eu
# pip install --user puts meson and ninja in ~/.local/bin, which is often not on PATH.
PATH="$HOME/.local/bin:$PATH"; export PATH
for t in git python3 gcc make cmake meson ninja; do
    command -v "$t" >/dev/null || { echo "missing tool: $t (see the header of this script)"; exit 1; }
done
LOG=${TMPDIR:-/tmp}/fetch_sources.$$.log
trap 'echo "failed; last lines of $LOG:"; tail -20 "$LOG"' EXIT
ROOT=${PQSIG_SOURCES:-$HOME/pqsig-src}
TOP=$(cd "$(dirname "$0")/.." && pwd)
SRC=$ROOT/src; NIST=$ROOT/nist
mkdir -p "$SRC" "$NIST"

get() { # get <dir> <url> <commit>
    # Blob-less clone: full history, file contents fetched only for the
    # commit we check out. Much smaller on a slow line. Three tries, since
    # a dropped connection kills a clone and git cannot resume it.
    n=0
    while [ ! -d "$SRC/$1/.git" ]; do
        n=$((n + 1))
        git -c http.version=HTTP/1.1 clone -q --filter=blob:none "$2" "$SRC/$1" && break
        rm -rf "$SRC/$1"
        [ $n -ge 3 ] && { echo "clone of $1 failed 3 times"; exit 1; }
        echo "clone of $1 failed, retrying in 10 s"; sleep 10
    done
    git -C "$SRC/$1" -c advice.detachedHead=false checkout -q "$3"
    echo "$1 $(git -C "$SRC/$1" rev-parse --short HEAD)"
}
get pqov         https://github.com/pqov/pqov.git                 fac2ec1
get MAYO-C       https://github.com/PQCMayo/MAYO-C.git            74de637
get faest-ref    https://github.com/faest-sign/faest-ref.git      04ce516
get the-sqisign  https://github.com/SQISign/the-sqisign.git       f417ebd
get SNOVA        https://github.com/PQCLAB-SNOVA/SNOVA.git        ebdd7e2
get mqom-v3      https://github.com/mqom/mqom-v3.git              920eea5
get sdith        https://github.com/sdith/sdith.git               ce7adf0
get qruov-round3 https://github.com/qruov/round3.git              3d84d0f
get mupq         https://github.com/mupq/mupq.git                 981df31
get pqclean      https://github.com/PQClean/PQClean.git           0586a82
get slhdsa-c     https://github.com/pq-code-package/slhdsa-c.git  b8553e8
get c-fn-dsa     https://github.com/pornin/c-fn-dsa.git           1b85888
get Monocypher   https://github.com/LoupVaillant/Monocypher.git   f5f0a19
get micro-ecc    https://github.com/kmackay/micro-ecc.git         541b3a7

echo "[uov] NIST layout"
( cd "$SRC/pqov" && rm -rf "$NIST/uov" && python3 create_nist_project.py "$NIST/uov" >> "$LOG" 2>&1 )

echo "[snova] parameter folders"
( cd "$SRC/SNOVA/dist" && python3 makesnova.py >> "$LOG" 2>&1 )

echo "[sqisign] pqm4 export"
( cd "$SRC/the-sqisign" && rm -rf src/pqm4 \
  && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >> "$LOG" 2>&1 \
  && cmake --build build -j2 --target PQCgenKAT_sign_pqm4_p324_3 PQCgenKAT_sign_pqm4_p500_27 PQCgenKAT_sign_pqm4_p664_17 >> "$LOG" 2>&1 \
  && bash scripts/gen_pqm4_sources.sh ref >> "$LOG" 2>&1 )

echo "[faest] meson build and NIST layout"
( cd "$SRC/faest-ref" && rm -rf build "$NIST/faest" \
  && meson setup build -Dbuildtype=release >> "$LOG" 2>&1 && ninja -C build >> "$LOG" 2>&1 \
  && python3 tools/prepare_nist.py . build "$NIST/faest" \
       faest_128f faest_128s faest_em_128f faest_em_128s faest_192f faest_192s \
       faest_em_192f faest_em_192s faest_256f faest_256s faest_em_256f faest_em_256s >> "$LOG" 2>&1 )

echo "[sdith] NIST layout"
( cd "$SRC/sdith" && rm -rf "$NIST/sdith" && python3 utils/make_nist_package.py --out "$NIST/sdith" --kats copy >> "$LOG" 2>&1 )

echo "[mqom] reference KATs from the team Makefile"
for v in $(ls "$SRC/mqom-v3/parameters" | sed 's/mqom3_parameters_//;s/\.h$//'); do
    MQOM_SRC="$SRC/mqom-v3" sh "$TOP/tools/checks/mqom_reference_kat.sh" "$v" "$NIST/mqom_ref"
    echo "  $v"
done
trap - EXIT
echo "done: sources in $ROOT"
