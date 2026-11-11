/*
 * prim.h - pqsig-eval portable replacement for QR-UOV's src/prim.h.
 *
 * QR-UOV's own prim.h/prim.c call OpenSSL (EVP SHAKE and AES-128-CTR).
 * ESP-IDF, MicroBlaze and CUDA have no OpenSSL, so this header keeps the
 * same API and prim_portable.c implements it with the mupq Keccak and the
 * PQClean constant-time AES in harness/common. KAT equality with the
 * team's KAT_SHA256SUMS.txt checks the replacement.
 */
#ifndef PRIM_H
#define PRIM_H

#include <stddef.h>
#include <stdint.h>

/* Opaque storage, large enough for the mupq incremental contexts. */
typedef struct shake256 {
    uint64_t st[26];        /* shake256incctx: 25 lanes + position */
    int squeezing;
} shake256;

typedef struct shake128 {
    uint64_t st[26];
    int squeezing;
} shake128;

typedef struct aes128 {
    uint64_t sk_exp[88];    /* PQClean aes128ctx, PQC_AES128_STATESIZE */
} aes128;

void shake256_init(shake256 *ctx);
void shake256_reset(shake256 *ctx);
void shake256_update(shake256 *ctx, const uint8_t *data, size_t size);
void shake256_digestfinal(shake256 *ctx, uint8_t *dst, size_t size);
void shake256_squeeze(shake256 *ctx, uint8_t *dst, size_t size);
void shake256_free(shake256 *ctx);

void shake128_init(shake128 *ctx);
void shake128_update(shake128 *ctx, const uint8_t *data, size_t size);
void shake128_digestfinal(shake128 *ctx, uint8_t *dst, size_t size);
void shake128_free(shake128 *ctx);

void aes128ctr_init(aes128 *ctx, const uint8_t key[16]);
void aes128ctr_stream(aes128 *ctx, const uint8_t iv[8], uint8_t *dst, size_t size);
void aes128ctr_free(aes128 *ctx);

#endif /* PRIM_H */
