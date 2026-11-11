/*
 * cpu_batch_verify.c - CPU batch verification for RQ4 (gateway throughput).
 *
 * Usage: cpu_batch_verify MODE BATCH REPS [THREADS]
 *   MODE    shared   one key pair signs the whole batch (one device, many readings)
 *           distinct one key pair per signature (a gateway serving many devices)
 *   BATCH   number of signatures, for example 1, 64, 1024, 16384 or 65536
 *   REPS    timed repetitions of the whole batch
 *   THREADS OpenMP threads (default: omp_get_max_threads(), i.e. every hardware thread)
 *
 * Each signature signs its own 32-byte message from the harness DRBG. One
 * signature in the batch, at index BATCH/2, gets one flipped byte and must
 * be rejected; every other signature must verify. A repetition with any
 * wrong accept or reject is reported with all_ok=0 and the paper must not
 * use it.
 *
 * Timing: CLOCK_MONOTONIC around the OpenMP parallel loop only. Key
 * generation and signing happen before timing starts (on all threads when
 * built with HARNESS_RNG_TLS; a NOTE,setup row gives the thread count).
 *
 * BATCH_DUMP=file writes the batch (keys, signed messages, expected
 * results) so the GPU program verifies exactly the same inputs:
 *   u64 n, mlen, smlen_max, pklen, mode(0 shared,1 distinct), flip_index
 *   then for each key (1 or n): pk bytes
 *   then for each i: u64 smlen, sm bytes (smlen_max, zero padded), u8 expect,
 *                    m bytes (mlen, the original message)
 * gpu/gpu_batch_verify.c reads this file.
 *
 * Output: BATCH,scheme,param,variant,platform,device,mode,threads,batch,rep,ns,verifies_per_s,all_ok
 */
#define _POSIX_C_SOURCE 200809L
#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "api.h"

#ifndef HARNESS_LEN_T
#define HARNESS_LEN_T unsigned long long
#endif

void harness_drbg_init(const unsigned char entropy[48]);
void harness_drbg_bytes(unsigned char *x, size_t n);

#define MLEN 32
#define SMMAX (MLEN + CRYPTO_BYTES)

static uint64_t now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

/* Key generation and signing happen before timing and are not measured.
 * With HARNESS_RNG_TLS (hbuild sets it for this program) they run on all
 * threads, each thread with its own DRBG state and seed, which cuts the
 * setup of a 65,536-signature batch from hours to minutes for the slow
 * signers. BATCH_SETUP_THREADS=1 restores the single-thread setup. */
static int setup_threads(int threads)
{
    const char *v = getenv("BATCH_SETUP_THREADS");
#ifdef HARNESS_RNG_TLS
    return (v && atoi(v) > 0) ? atoi(v) : threads;
#else
    (void)threads;
    (void)v;
    return 1;
#endif
}

#ifdef HARNESS_RNG_TLS
/* Returns 1 when every signature verifies in an untimed check pass, so a
 * package with hidden shared state cannot give a wrong batch; otherwise 0
 * and the caller sets the batch up again on one thread. */
static int setup_parallel(int st, const unsigned char e[48], int distinct, long n, unsigned char *pk,
                          const unsigned char *sk0, unsigned char *sm, unsigned char *m, HARNESS_LEN_T *smlen)
{
    long bad = 0;
    if (!distinct) {
        harness_drbg_init(e);
        crypto_sign_keypair(pk, (unsigned char *)sk0);
    }
#pragma omp parallel num_threads(st) reduction(+ : bad)
    {
        unsigned char te[48];
        int tid = omp_get_thread_num();
        memcpy(te, e, 48);
        te[46] ^= (unsigned char)(tid >> 8);
        te[47] ^= (unsigned char)(tid & 0xFF);
        te[45] ^= 0x5A;
        harness_drbg_init(te);
        unsigned char *sk = malloc(CRYPTO_SECRETKEYBYTES);
        unsigned char *out = malloc(SMMAX);
        if (!sk || !out) {
            bad++;
        } else {
            if (!distinct) {
                memcpy(sk, sk0, CRYPTO_SECRETKEYBYTES);
            }
#pragma omp for schedule(dynamic, 16)
            for (long i = 0; i < n; i++) {
                if (distinct) {
                    crypto_sign_keypair(pk + (size_t)i * CRYPTO_PUBLICKEYBYTES, sk);
                }
                harness_drbg_bytes(m + (size_t)i * MLEN, MLEN);
                crypto_sign(sm + (size_t)i * SMMAX, &smlen[i], m + (size_t)i * MLEN, MLEN, sk);
            }
#pragma omp for schedule(dynamic, 16)
            for (long i = 0; i < n; i++) {
                HARNESS_LEN_T ml;
                const unsigned char *kp = pk + (size_t)(distinct ? i : 0) * CRYPTO_PUBLICKEYBYTES;
                if (crypto_sign_open(out, &ml, sm + (size_t)i * SMMAX, smlen[i], kp) != 0 || ml != MLEN ||
                    memcmp(out, m + (size_t)i * MLEN, MLEN) != 0) {
                    bad++;
                }
            }
        }
        free(sk);
        free(out);
    }
    return bad == 0;
}
#endif

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: cpu_batch_verify shared|distinct BATCH REPS [THREADS]\n");
        return 2;
    }
    int distinct = strcmp(argv[1], "distinct") == 0;
    if (!distinct && strcmp(argv[1], "shared") != 0) {
        fprintf(stderr, "MODE must be shared or distinct\n");
        return 2;
    }
    long n = atol(argv[2]);
    int reps = atoi(argv[3]);
    int threads = (argc > 4) ? atoi(argv[4]) : omp_get_max_threads();
    long nkeys = distinct ? n : 1;
    long flip = n / 2;

    unsigned char e[48];
    for (int i = 0; i < 48; i++) {
        e[i] = (unsigned char)(0xB7 ^ i);
    }
    unsigned char *pk = malloc((size_t)nkeys * CRYPTO_PUBLICKEYBYTES);
    unsigned char *sk = malloc(CRYPTO_SECRETKEYBYTES);
    unsigned char *sm = calloc((size_t)n, SMMAX);
    unsigned char *m = malloc((size_t)n * MLEN);
    HARNESS_LEN_T *smlen = malloc((size_t)n * sizeof(HARNESS_LEN_T));
    unsigned char *expect = malloc((size_t)n);
    unsigned char *got = malloc((size_t)n);
    if (!pk || !sk || !sm || !m || !smlen || !expect || !got) {
        printf("ERROR,alloc_failed,batch,%ld\n", n);
        return 1;
    }
    uint64_t s0 = now_ns();
    int st = setup_threads(threads);
    int done = 0;
#ifdef HARNESS_RNG_TLS
    if (st > 1) {
        done = setup_parallel(st, e, distinct, n, pk, sk, sm, m, smlen);
        if (!done) {
            printf("NOTE,parallel_setup_check_failed,batch,%ld,setup_again_on_one_thread\n", n);
            st = 1;
        }
    }
#endif
    if (!done) {
        harness_drbg_init(e);
        for (long i = 0; i < n; i++) {
            if (i < nkeys) {
                crypto_sign_keypair(pk + (size_t)i * CRYPTO_PUBLICKEYBYTES, sk);
            }
            harness_drbg_bytes(m + (size_t)i * MLEN, MLEN);
            crypto_sign(sm + (size_t)i * SMMAX, &smlen[i], m + (size_t)i * MLEN, MLEN, sk);
        }
    }
    for (long i = 0; i < n; i++) {
        expect[i] = 1;
    }
    printf("NOTE,setup,threads,%d,batch,%ld,s,%.1f\n", st, n, (double)(now_ns() - s0) / 1e9);
    /* Flip byte 0 of one signed message. Depending on the package's layout
     * (signature || message or message || signature) this changes either
     * the signature or the signed message; both must make verification fail. */
    sm[(size_t)flip * SMMAX] ^= 0x01;
    expect[flip] = 0;

    const char *dump = getenv("BATCH_DUMP");
    if (dump) {
        FILE *f = fopen(dump, "wb");
        if (!f) {
            printf("ERROR,batch_dump_open\n");
            return 1;
        }
        uint64_t hdr[6] = {(uint64_t)n, MLEN, SMMAX, CRYPTO_PUBLICKEYBYTES, (uint64_t)distinct, (uint64_t)flip};
        fwrite(hdr, sizeof hdr, 1, f);
        fwrite(pk, CRYPTO_PUBLICKEYBYTES, (size_t)nkeys, f);
        for (long i = 0; i < n; i++) {
            uint64_t l = (uint64_t)smlen[i];
            fwrite(&l, sizeof l, 1, f);
            fwrite(sm + (size_t)i * SMMAX, 1, SMMAX, f);
            fwrite(&expect[i], 1, 1, f);
            fwrite(m + (size_t)i * MLEN, 1, MLEN, f);
        }
        fclose(f);
    }

    printf("BATCH_HDR,scheme,param,variant,platform,device,mode,threads,batch,rep,ns,verifies_per_s,all_ok\n");
    omp_set_num_threads(threads);
    for (int r = 0; r < reps; r++) {
        memset(got, 0xFF, (size_t)n);
        uint64_t t0 = now_ns();
#pragma omp parallel
        {
            unsigned char *out = malloc(SMMAX);
            HARNESS_LEN_T mlen;
#pragma omp for schedule(static)
            for (long i = 0; i < n; i++) {
                const unsigned char *kp = pk + (size_t)(distinct ? i : 0) * CRYPTO_PUBLICKEYBYTES;
                int rc = crypto_sign_open(out, &mlen, sm + (size_t)i * SMMAX, smlen[i], kp);
                got[i] = (unsigned char)(rc == 0 && mlen == MLEN && memcmp(out, m + (size_t)i * MLEN, MLEN) == 0);
            }
            free(out);
        }
        uint64_t t1 = now_ns();
        int ok = memcmp(got, expect, (size_t)n) == 0;
        printf("BATCH,%s,%s,%s,%s,cpu,%s,%d,%ld,%d,%llu,%.1f,%d\n", HARNESS_SCHEME, HARNESS_PARAM,
               HARNESS_VARIANT, HARNESS_PLATFORM, distinct ? "distinct" : "shared", threads, n, r,
               (unsigned long long)(t1 - t0), (double)n / ((double)(t1 - t0) / 1e9), ok);
        fflush(stdout);
    }
    return 0;
}
