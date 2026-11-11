/*
 * kernel.c - batch verification kernel: one GPU thread per signature.
 *
 * This file and the scheme's own portable C sources are compiled with
 * clang --target=nvptx64-nvidia-cuda (see gpu/build_gpu.py). The thread
 * calls the package's crypto_sign_open() unchanged, so the GPU runs the
 * same verification code as the ESP32 and the CPU reference builds. It is
 * a direct port, not a GPU-optimised implementation, and the paper says so.
 *
 * Inputs follow the BATCH_DUMP file of gpu/cpu_batch_verify.c:
 *   pk     one key (shared mode, pk_stride = 0) or one per signature
 *   sm     signed messages, one every smlen_max bytes (a multiple of 16,
 *          so every message starts aligned), zero padded
 *   smlen  real length of each signed message
 *   m      the original messages, mlen bytes each
 * Output: got[i] = 1 when crypto_sign_open accepts and returns exactly the
 * original message, the same rule as the CPU batch verifier.
 *
 * The bench_defines of the recipe rename crypto_sign_open where a package
 * uses a namespaced name (PQClean).
 */
#include <stdint.h>
#include <stddef.h>

#ifndef HARNESS_LEN_T
#define HARNESS_LEN_T unsigned long long
#endif

/* The package's api.h, as bench_main.c uses it: several packages rename
 * crypto_sign_open there (UOV, PQClean through bench_defines). */
#ifdef PQG_HAVE_API
#include "api.h"
#else
int crypto_sign_open(unsigned char *m, HARNESS_LEN_T *mlen, const unsigned char *sm,
                     HARNESS_LEN_T smlen, const unsigned char *pk);
#endif

static int same(const unsigned char *a, const unsigned char *b, uint64_t n)
{
    unsigned char d = 0;
    for (uint64_t i = 0; i < n; i++) {
        d |= (unsigned char)(a[i] ^ b[i]);
    }
    return d == 0;
}

__attribute__((nvptx_kernel)) void pq_verify(const unsigned char *pk, uint64_t pk_stride,
                                             const unsigned char *sm, const uint64_t *smlen,
                                             uint64_t smlen_max, const unsigned char *m,
                                             uint64_t mlen, unsigned char *mout, uint64_t first,
                                             uint64_t count, unsigned char *got)
{
    uint64_t t = (uint64_t)__nvvm_read_ptx_sreg_ctaid_x() * (uint64_t)__nvvm_read_ptx_sreg_ntid_x()
                 + (uint64_t)__nvvm_read_ptx_sreg_tid_x();
    if (t >= count) {
        return;
    }
    uint64_t i = first + t;
    unsigned char *out = mout + i * smlen_max;
    HARNESS_LEN_T outlen = 0;
    int rc = crypto_sign_open(out, &outlen, sm + i * smlen_max, (HARNESS_LEN_T)smlen[i],
                              pk + i * pk_stride);
    got[i] = (unsigned char)(rc == 0 && (uint64_t)outlen == mlen && same(out, m + i * mlen, mlen));
}
