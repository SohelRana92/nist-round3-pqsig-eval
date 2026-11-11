/*
 * fixvsrand_sign.c - fixed-versus-random secret-key timing test for
 * crypto_sign, after the method of dudect (Reparaz, Balasch and
 * Verbauwhede, DATE 2017).
 *
 * Class 0 signs with one fixed secret key. Class 1 signs with a key drawn
 * from a pool of fresh random keys. The message is the same for both.
 * Both classes read their key from a pool of POOL_KEYS slots chosen the
 * same way: class 0's pool holds copies of the fixed key, and the slots of
 * both classes are interleaved at random in one buffer. The two classes
 * then touch the same amount of memory, so a large secret key (UOV keeps
 * about 237 KB) does not make class 1 slower through cache misses alone.
 * The first version used a single buffer for class 0 and reported that
 * cache effect as a leak (|t| up to 1,869 for UOV).
 * The class of each measurement is random. Welch's t statistic is updated
 * online for the raw times and for times cropped at 10 percentiles fixed
 * from a warm-up batch, as dudect does. The largest |t| is reported.
 *
 * Usage: ct_fixvsrand N_MEASUREMENTS [POOL_KEYS] [SEED]
 *   SEED (0-255, default 92) changes the keys, message and class sequence,
 *   for a confirmation run with fresh data.
 *   CT_FRESHCOPY=1 copies the chosen key, before every measurement, into a
 *   work slot picked at random for that measurement from one shared set.
 *   Both classes then sign from the same addresses with the key just
 *   written (same cache state). Version 3's fixed slot sets still left the
 *   fixed-versus-fixed control above 4.5 for UOV (237 KB keys: |t| = 6 and
 *   15): which slots a class happened to own mattered. Rows then carry the
 *   suffix _fresh.
 *   CT_CONTROL=1 in the environment fills class 1's pool with copies of the
 *   fixed key too (fixed-versus-fixed). Both classes then sign with the same
 *   key from different buffers, so any |t| above 4.5 comes from the set-up,
 *   not from the key: the false-positive control.
 * Output: CT,scheme,param,variant,platform,test,n,max_abs_t,result
 * result "leak" if max |t| > 4.5 (the usual TVLA threshold).
 */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "api.h"
#include "harness.h"

#ifndef HARNESS_LEN_T
#define HARNESS_LEN_T unsigned long long
#endif

void harness_drbg_init(const unsigned char entropy[48]);
void harness_drbg_bytes(unsigned char *x, size_t n);

#define NCROP 10
#define WARM 1000

typedef struct {
    double n[2], mean[2], m2[2];
} welch_t;

static void wpush(welch_t *w, int c, double x)
{
    w->n[c] += 1;
    double d = x - w->mean[c];
    w->mean[c] += d / w->n[c];
    w->m2[c] += d * (x - w->mean[c]);
}

static double wstat(const welch_t *w)
{
    if (w->n[0] < 2 || w->n[1] < 2) {
        return 0;
    }
    double v0 = w->m2[0] / (w->n[0] - 1), v1 = w->m2[1] / (w->n[1] - 1);
    double den = sqrt(v0 / w->n[0] + v1 / w->n[1]);
    return den > 0 ? (w->mean[0] - w->mean[1]) / den : 0;
}

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv)
{
    long n = (argc > 1) ? atol(argv[1]) : 100000;
    int pool = (argc > 2) ? atoi(argv[2]) : 64;
    int seed = (argc > 3) ? atoi(argv[3]) : 0x5C;
    const char *ctl = getenv("CT_CONTROL");
    int control = ctl != NULL && ctl[0] == '1';
    const char *fc = getenv("CT_FRESHCOPY");
    int fresh = fc != NULL && fc[0] == '1';
    unsigned char e[48];
    for (int i = 0; i < 48; i++) {
        e[i] = (unsigned char)((seed & 0xFF) ^ i);
    }
    plat_init();
    harness_drbg_init(e);

    unsigned char *pk = malloc(CRYPTO_PUBLICKEYBYTES);
    /* All 2*POOL key slots live in one buffer, 64-byte aligned, and a random
       permutation decides which slots belong to which class. Two separate
       buffers (version 2 of this test) differ in page placement, and the
       fixed-versus-fixed control then still gave |t| = 35 (UOV ref) and 120
       (UOV GFNI): the difference came from where the keys lived, not from
       their values. */
    size_t stride = ((size_t)CRYPTO_SECRETKEYBYTES + 63) & ~(size_t)63;
    unsigned char *keys = NULL;
    if (posix_memalign((void **)&keys, 64, 2 * (size_t)pool * stride) != 0) {
        keys = NULL;
    }
    size_t *slot_of = malloc(2 * (size_t)pool * sizeof(size_t));
    unsigned char *work = NULL;
    if (fresh && posix_memalign((void **)&work, 64, (size_t)pool * stride) != 0) {
        fprintf(stderr, "alloc failed\n");
        return 1;
    }
    unsigned char m[32];
    unsigned char *sm = malloc(32 + CRYPTO_BYTES);
    HARNESS_LEN_T smlen;
    if (!pk || !keys || !slot_of || !sm) {
        fprintf(stderr, "alloc failed\n");
        return 1;
    }
    for (size_t i = 0; i < 2 * (size_t)pool; i++) {
        slot_of[i] = i;
    }
    for (size_t i = 2 * (size_t)pool - 1; i > 0; i--) {     /* Fisher-Yates */
        uint32_t r;
        harness_drbg_bytes((unsigned char *)&r, sizeof r);
        size_t j = r % (i + 1), t = slot_of[i];
        slot_of[i] = slot_of[j];
        slot_of[j] = t;
    }
    /* slot_of[c * pool + k] is the k-th key of class c */
    unsigned char *sk0 = keys + slot_of[0] * stride;
    crypto_sign_keypair(pk, sk0);
    for (int k = 1; k < pool; k++) {
        memcpy(keys + slot_of[k] * stride, sk0, CRYPTO_SECRETKEYBYTES);
    }
    for (int k = 0; k < pool; k++) {
        unsigned char *dst = keys + slot_of[pool + k] * stride;
        if (control) {
            memcpy(dst, sk0, CRYPTO_SECRETKEYBYTES);
        } else {
            crypto_sign_keypair(pk, dst);
        }
    }
    harness_drbg_bytes(m, sizeof m);

    welch_t raw;
    welch_t crop[NCROP];
    memset(&raw, 0, sizeof raw);
    memset(crop, 0, sizeof crop);
    uint64_t thr[NCROP];
    uint64_t *warm = malloc(WARM * sizeof(uint64_t));
    long wn = 0;
    double maxt = 0;

    for (long i = 0; i < n + WARM; i++) {
        unsigned char rb;
        harness_drbg_bytes(&rb, 1);
        int cls = rb & 1;
        size_t k = (size_t)(rb >> 1) % (size_t)pool;
        const unsigned char *sk = keys + slot_of[(size_t)cls * (size_t)pool + k] * stride;
        if (fresh) {
            unsigned char wb;
            harness_drbg_bytes(&wb, 1);
            unsigned char *dst = work + (size_t)(wb % (unsigned)pool) * stride;
            memcpy(dst, sk, CRYPTO_SECRETKEYBYTES);
            sk = dst;
        }
        plat_stamp_t a, b;
        plat_stamp(&a);
        crypto_sign(sm, &smlen, m, sizeof m, sk);
        plat_stamp(&b);
        uint64_t t = plat_cycles_between(&a, &b);
        if (wn < WARM) {
            warm[wn++] = t;
            if (wn == WARM) {
                qsort(warm, WARM, sizeof(uint64_t), cmp_u64);
                for (int k = 0; k < NCROP; k++) {
                    /* dudect-style thresholds: 1 - 0.5^(10(k+1)/NCROP) */
                    double p = 1.0 - pow(0.5, 10.0 * (k + 1) / NCROP);
                    thr[k] = warm[(long)(p * (WARM - 1))];
                }
            }
            continue;
        }
        wpush(&raw, cls, (double)t);
        for (int k = 0; k < NCROP; k++) {
            if (t < thr[k]) {
                wpush(&crop[k], cls, (double)t);
            }
        }
    }
    maxt = fabs(wstat(&raw));
    for (int k = 0; k < NCROP; k++) {
        double tt = fabs(wstat(&crop[k]));
        if (tt > maxt) {
            maxt = tt;
        }
    }
    printf("CT_HDR,scheme,param,variant,platform,test,n,max_abs_t,result\n");
    const char *test = control ? "fixvsfix_control" : (seed != 0x5C ? "fixvsrand_confirm" : "fixvsrand_sign");
    printf("CT,%s,%s,%s,%s,%s%s,%ld,%.3f,%s\n", HARNESS_SCHEME, HARNESS_PARAM,
           HARNESS_VARIANT, HARNESS_PLATFORM, test, fresh ? "_fresh" : "", n, maxt,
           maxt > 4.5 ? "leak" : "no_leak_detected");
    return 0;
}
