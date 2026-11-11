/*
 * bench_main.c - one benchmark driver for every scheme and platform.
 *
 * Modes:
 *   sizes                      key and signature sizes from api.h
 *   kat N                      first N vectors of the NIST KAT sequence,
 *                              as SHA-256 digests of pk, sk and sm
 *   speed RUNS WARMUP          cycles and nanoseconds per operation
 *   stack                      peak stack per operation
 *   energy OP SECONDS WINDOWS  loop one operation with the marker pin high
 *
 * Every output line is CSV. The first field names the record type.
 * On Linux the mode comes from argv. On ESP32 and MicroBlaze the
 * platform file calls harness_run() with a fixed argument list.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "api.h"
#include "harness.h"

/* Declared here, not via rng.h: a package rng.h may redefine randombytes. */
void harness_drbg_init(const unsigned char entropy[48]);
void harness_drbg_bytes(unsigned char *x, size_t n);
#include "hsha256.h"

#ifndef HARNESS_SPEED_RUNS
#define HARNESS_SPEED_RUNS 1000
#endif
#ifndef HARNESS_SPEED_WARMUP
#define HARNESS_SPEED_WARMUP 10
#endif
#ifndef HARNESS_SLOW_RUNS
#define HARNESS_SLOW_RUNS 100     /* used when one operation exceeds 1 s */
#endif
/* A second step for very slow cores (MicroBlaze at 81 MHz): if one run
 * exceeds HARNESS_VERY_SLOW_NS, use HARNESS_VERY_SLOW_RUNS. Off unless a
 * platform build defines both. */
#ifndef HARNESS_VERY_SLOW_NS
#define HARNESS_VERY_SLOW_NS 0ULL
#endif
#ifndef HARNESS_VERY_SLOW_RUNS
#define HARNESS_VERY_SLOW_RUNS HARNESS_SLOW_RUNS
#endif
#define MSG_LEN 32

/* Length type of the scheme's crypto_sign API (unsigned long long in the
 * NIST template, size_t in some packages). Set by the recipe. */
#ifndef HARNESS_LEN_T
#define HARNESS_LEN_T unsigned long long
#endif

static unsigned char *g_pk, *g_sk, *g_sm, *g_m, *g_m2;
static HARNESS_LEN_T g_smlen;
static char g_line[512];

static void out(void)
{
    plat_puts(g_line);
}

static void hexify(const unsigned char *in, size_t n, char *hex)
{
    static const char d[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        hex[2 * i] = d[in[i] >> 4];
        hex[2 * i + 1] = d[in[i] & 15];
    }
    hex[2 * n] = '\0';
}

static int alloc_buffers(size_t max_mlen)
{
    g_pk = plat_alloc(CRYPTO_PUBLICKEYBYTES);
    g_sk = plat_alloc(CRYPTO_SECRETKEYBYTES);
    g_sm = plat_alloc(max_mlen + CRYPTO_BYTES);
    g_m = plat_alloc(max_mlen + 1);
    g_m2 = plat_alloc(max_mlen + CRYPTO_BYTES);
    if (!g_pk || !g_sk || !g_sm || !g_m || !g_m2) {
        snprintf(g_line, sizeof g_line,
                 "ERROR,%s,%s,%s,%s,alloc_failed,pk=%lu,sk=%lu,sig=%lu",
                 HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
                 (unsigned long)CRYPTO_PUBLICKEYBYTES,
                 (unsigned long)CRYPTO_SECRETKEYBYTES,
                 (unsigned long)CRYPTO_BYTES);
        out();
        return -1;
    }
    return 0;
}

static void free_buffers(void)
{
    plat_free(g_pk);
    plat_free(g_sk);
    plat_free(g_sm);
    plat_free(g_m);
    plat_free(g_m2);
}

/* ---------- sizes ---------- */

static void mode_sizes(void)
{
    plat_puts("SIZES_HDR,scheme,param,variant,platform,pk_bytes,sk_bytes,sig_bytes");
    snprintf(g_line, sizeof g_line, "SIZES,%s,%s,%s,%s,%lu,%lu,%lu",
             HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
             (unsigned long)CRYPTO_PUBLICKEYBYTES,
             (unsigned long)CRYPTO_SECRETKEYBYTES,
             (unsigned long)CRYPTO_BYTES);
    out();
}

/* ---------- KAT ----------
 * Same sequence as NIST PQCgenKAT_sign.c: one DRBG seeded with
 * entropy 0,1,...,47 draws seed_i (48 bytes) and msg_i (33*(i+1) bytes)
 * in turn. Each vector then reseeds with seed_i and runs
 * keypair, sign and open. */
static int mode_kat(int n)
{
    unsigned char entropy[48];
    unsigned char seed[48];
    char hpk[65], hsk[65], hsm[65];
    int fails = 0;

    if (alloc_buffers(33 * (size_t)n) != 0) {
        return 1;
    }
    plat_puts("KAT_HDR,scheme,param,variant,platform,count,sha256_pk,sha256_sk,smlen,sha256_sm,open_ok");
    for (int i = 0; i < 48; i++) {
        entropy[i] = (unsigned char)i;
    }
    /* Draw all seeds and messages first, as PQCgenKAT does. */
    unsigned char *seeds = plat_alloc(48 * (size_t)n);
    if (!seeds) {
        plat_puts("ERROR,kat_seed_alloc");
        free_buffers();
        return 1;
    }
    size_t msg_total = 0;
    for (int c = 0; c < n; c++) {
        msg_total += 33 * (size_t)(c + 1);
    }
    unsigned char *msgs = plat_alloc(msg_total);
    if (!msgs) {
        plat_puts("ERROR,kat_msg_alloc");
        plat_free(seeds);
        free_buffers();
        return 1;
    }
    harness_drbg_init(entropy);
    size_t off = 0;
    for (int c = 0; c < n; c++) {
        harness_drbg_bytes(seeds + 48 * c, 48);
        harness_drbg_bytes(msgs + off, 33 * (size_t)(c + 1));
        off += 33 * (size_t)(c + 1);
    }
    off = 0;
    for (int c = 0; c < n; c++) {
        HARNESS_LEN_T mlen = (HARNESS_LEN_T)(33 * (c + 1));
        HARNESS_LEN_T mlen1 = 0;
        memcpy(seed, seeds + 48 * c, 48);
        harness_drbg_init(seed);
        int r = crypto_sign_keypair(g_pk, g_sk);
        if (r == 0) {
            r = crypto_sign(g_sm, &g_smlen, msgs + off, mlen, g_sk);
        }
        int ok = 0;
        if (r == 0) {
            ok = (crypto_sign_open(g_m2, &mlen1, g_sm, g_smlen, g_pk) == 0) &&
                 (mlen1 == mlen) && (memcmp(g_m2, msgs + off, (size_t)mlen) == 0);
        }
        if (!ok) {
            fails++;
        }
        h_sha256_hex(g_pk, CRYPTO_PUBLICKEYBYTES, hpk);
        h_sha256_hex(g_sk, CRYPTO_SECRETKEYBYTES, hsk);
        h_sha256_hex(g_sm, (size_t)g_smlen, hsm);
        snprintf(g_line, sizeof g_line, "KAT,%s,%s,%s,%s,%d,%s,%s,%llu,%s,%d",
                 HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
                 c, hpk, hsk, (unsigned long long)g_smlen, hsm, ok);
        out();
        off += (size_t)mlen;
    }
    plat_free(msgs);
    plat_free(seeds);
    free_buffers();
    return fails ? 1 : 0;
}

/* ---------- speed ---------- */

static void seed_bench_rng(void)
{
    unsigned char entropy[48];
    for (int i = 0; i < 48; i++) {
        entropy[i] = (unsigned char)(0xA0 ^ i);
    }
    harness_drbg_init(entropy);
}

static void print_speed(const char *op, int run, uint64_t cyc, uint64_t ns,
                        const char *msg_hex, int ok)
{
    snprintf(g_line, sizeof g_line, "SPEED,%s,%s,%s,%s,%s,%s,%d,%llu,%llu,%s,%s,%d",
             HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
             plat_timer_name(), op, run,
             (unsigned long long)cyc, (unsigned long long)ns,
             msg_hex, HARNESS_CFLAGS, ok);
    out();
}

/* Run one operation once and return its wall time in ns. */
typedef int (*op_fn)(void);

static int op_keypair(void)
{
    return crypto_sign_keypair(g_pk, g_sk);
}

static int op_sign(void)
{
    return crypto_sign(g_sm, &g_smlen, g_m, MSG_LEN, g_sk);
}

static int op_noop(void)
{
    return 0;
}

static int op_open(void)
{
    HARNESS_LEN_T mlen1 = 0;
    int r = crypto_sign_open(g_m2, &mlen1, g_sm, g_smlen, g_pk);
    if (r == 0 && (mlen1 != MSG_LEN || memcmp(g_m2, g_m, MSG_LEN) != 0)) {
        r = -1;
    }
    return r;
}

static void bench_op(const char *name, op_fn fn, int runs, int warmup,
                     int new_msg, int need_sign_first)
{
    plat_stamp_t a, b;
    char msg_hex[2 * MSG_LEN + 1];

    for (int w = 0; w < warmup; w++) {
        if (new_msg) {
            harness_drbg_bytes(g_m, MSG_LEN);
        }
        if (need_sign_first) {
            op_sign();
        }
        fn();
    }
    for (int i = 0; i < runs; i++) {
        if (new_msg) {
            harness_drbg_bytes(g_m, MSG_LEN);
        }
        if (need_sign_first) {
            op_sign();
        }
        plat_stamp(&a);
        int r = fn();
        plat_stamp(&b);
        uint64_t ns = b.ns - a.ns;
        if (new_msg) {
            hexify(g_m, MSG_LEN, msg_hex);
        } else {
            strcpy(msg_hex, "-");
        }
        print_speed(name, i, plat_cycles_between(&a, &b), ns, msg_hex, r == 0);
        /* Rule: if one operation takes over 1 s, use 100 runs. */
        if (i == 0 && ns > 1000000000ULL && runs > HARNESS_SLOW_RUNS) {
            runs = HARNESS_SLOW_RUNS;
            if (HARNESS_VERY_SLOW_NS > 0 && ns > HARNESS_VERY_SLOW_NS && runs > HARNESS_VERY_SLOW_RUNS) {
                runs = HARNESS_VERY_SLOW_RUNS;
            }
            snprintf(g_line, sizeof g_line, "NOTE,%s,%s,%s,%s,%s,runs_reduced_to,%d",
                     HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
                     name, runs);
            out();
        }
    }
}

static int mode_speed(int runs, int warmup)
{
    if (alloc_buffers(MSG_LEN) != 0) {
        return 1;
    }
    plat_puts("SPEED_HDR,scheme,param,variant,platform,timer,op,run,cycles,ns,msg_hex,cflags,ok");
    seed_bench_rng();
    bench_op("keypair", op_keypair, runs, warmup, 0, 0);
    /* One fixed key for signing and verification. */
    op_keypair();
    bench_op("sign", op_sign, runs, warmup, 1, 0);
    bench_op("verify", op_open, runs, warmup, 1, 1);
    free_buffers();
    return 0;
}

/* ---------- stack ---------- */

struct stack_job {
    op_fn fn;
    int ret;
};

static void stack_tramp(void *arg)
{
    struct stack_job *j = (struct stack_job *)arg;
    j->ret = j->fn();
}

static int mode_stack(void)
{
    struct stack_job j;
    if (alloc_buffers(MSG_LEN) != 0) {
        return 1;
    }
    plat_puts("STACK_HDR,scheme,param,variant,platform,op,peak_stack_bytes,ok");
    seed_bench_rng();
    harness_drbg_bytes(g_m, MSG_LEN);

    /* "noop" is the thread-start baseline; subtract it from the others. */
    const char *names[4] = { "noop", "keypair", "sign", "verify" };
    op_fn fns[4] = { op_noop, op_keypair, op_sign, op_open };
    for (int k = 0; k < 4; k++) {
        j.fn = fns[k];
        j.ret = -1;
        size_t peak = plat_peak_stack(stack_tramp, &j);
        snprintf(g_line, sizeof g_line, "STACK,%s,%s,%s,%s,%s,%lu,%d",
                 HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
                 names[k], (unsigned long)peak, j.ret == 0);
        out();
    }
    free_buffers();
    return 0;
}

/* ---------- energy ---------- */

static int mode_energy(const char *op, double seconds, int windows)
{
    op_fn fn;
    int need_sign = 0;
    if (strcmp(op, "keypair") == 0) {
        fn = op_keypair;
    } else if (strcmp(op, "sign") == 0) {
        fn = op_sign;
    } else if (strcmp(op, "verify") == 0) {
        fn = op_open;
    } else if (strcmp(op, "idle") == 0) {
        fn = NULL;
    } else {
        plat_puts("ERROR,energy_unknown_op");
        return 1;
    }
    if (alloc_buffers(MSG_LEN) != 0) {
        return 1;
    }
    plat_puts("ENERGY_HDR,scheme,param,variant,platform,op,window,ops,window_ns");
    seed_bench_rng();
    harness_drbg_bytes(g_m, MSG_LEN);
    op_keypair();
    op_sign();
    (void)need_sign;
    uint64_t limit = (uint64_t)(seconds * 1e9);
    for (int w = 0; w < windows; w++) {
        plat_stamp_t a, b;
        unsigned long count = 0;
        plat_marker(1);
        plat_stamp(&a);
        do {
            if (fn) {
                fn();
            }
            count++;
            plat_stamp(&b);
        } while (b.ns - a.ns < limit);
        plat_marker(0);
        snprintf(g_line, sizeof g_line, "ENERGY,%s,%s,%s,%s,%s,%d,%lu,%llu",
                 HARNESS_SCHEME, HARNESS_PARAM, HARNESS_VARIANT, HARNESS_PLATFORM,
                 op, w, fn ? count : 0UL, (unsigned long long)(b.ns - a.ns));
        out();
        /* Rest 2 s between windows so the logger sees a clean low level.
         * The rest is the platform's idle (a sleep where it has one), so
         * E_op is the energy above an idle core, not above a busy wait. */
        plat_rest_ms(2000);
    }
    free_buffers();
    return 0;
}

/* ---------- entry ---------- */

int harness_run(int argc, char **argv)
{
    plat_init();
    if (argc < 2) {
        plat_puts("usage: bench sizes | kat N | speed RUNS WARMUP | stack | energy OP SECONDS WINDOWS");
        return 2;
    }
    const char *mode = argv[1];
    if (strcmp(mode, "sizes") == 0) {
        mode_sizes();
        return 0;
    }
    if (strcmp(mode, "kat") == 0) {
        int n = (argc > 2) ? atoi(argv[2]) : 10;
        return mode_kat(n);
    }
    if (strcmp(mode, "speed") == 0) {
        int runs = (argc > 2) ? atoi(argv[2]) : HARNESS_SPEED_RUNS;
        int warm = (argc > 3) ? atoi(argv[3]) : HARNESS_SPEED_WARMUP;
        return mode_speed(runs, warm);
    }
    if (strcmp(mode, "stack") == 0) {
        return mode_stack();
    }
    if (strcmp(mode, "energy") == 0) {
        const char *op = (argc > 2) ? argv[2] : "sign";
        double secs = (argc > 3) ? atof(argv[3]) : 10.0;
        int win = (argc > 4) ? atoi(argv[4]) : 5;
        return mode_energy(op, secs, win);
    }
    plat_puts("ERROR,unknown_mode");
    return 2;
}
