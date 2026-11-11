/*
 * prim_portable.c - QR-UOV primitives without OpenSSL.
 * Same behaviour as QR-UOV's src/prim.c:
 *   - SHAKE: update* then either one digestfinal or any number of squeezes.
 *   - AES-128-CTR: counter block = iv (8 bytes) || 0 (8 bytes), incremented
 *     as a 128-bit big-endian integer, as OpenSSL's EVP_aes_128_ctr does.
 */
#include <string.h>

/* mupq's fips202.h declares one-shot functions named shake128/shake256,
 * which clash with QR-UOV's type names. Rename them in this file only. */
#define shake128 pqsig_mupq_shake128
#define shake256 pqsig_mupq_shake256
#include "fips202.h"
#undef shake128
#undef shake256
#include "aes.h"
#include "prim.h"

_Static_assert(sizeof(shake256incctx) <= sizeof(((shake256 *)0)->st), "shake256 storage");
_Static_assert(sizeof(shake128incctx) <= sizeof(((shake128 *)0)->st), "shake128 storage");
_Static_assert(sizeof(aes128ctx) <= sizeof(((aes128 *)0)->sk_exp), "aes128 storage");

#define S256(c) ((shake256incctx *)(void *)(c)->st)
#define S128(c) ((shake128incctx *)(void *)(c)->st)
#define AESK(c) ((aes128ctx *)(void *)(c)->sk_exp)

void shake256_init(shake256 *ctx)
{
    shake256_inc_init(S256(ctx));
    ctx->squeezing = 0;
}

void shake256_reset(shake256 *ctx)
{
    shake256_inc_ctx_release(S256(ctx));
    shake256_init(ctx);
}

void shake256_update(shake256 *ctx, const uint8_t *data, size_t size)
{
    shake256_inc_absorb(S256(ctx), data, size);
}

void shake256_digestfinal(shake256 *ctx, uint8_t *dst, size_t size)
{
    shake256_inc_finalize(S256(ctx));
    shake256_inc_squeeze(dst, size, S256(ctx));
    ctx->squeezing = 1;
}

void shake256_squeeze(shake256 *ctx, uint8_t *dst, size_t size)
{
    if (!ctx->squeezing) {
        shake256_inc_finalize(S256(ctx));
        ctx->squeezing = 1;
    }
    shake256_inc_squeeze(dst, size, S256(ctx));
}

void shake256_free(shake256 *ctx)
{
    shake256_inc_ctx_release(S256(ctx));
    memset(ctx, 0, sizeof *ctx);
}

void shake128_init(shake128 *ctx)
{
    shake128_inc_init(S128(ctx));
    ctx->squeezing = 0;
}

void shake128_update(shake128 *ctx, const uint8_t *data, size_t size)
{
    shake128_inc_absorb(S128(ctx), data, size);
}

void shake128_digestfinal(shake128 *ctx, uint8_t *dst, size_t size)
{
    shake128_inc_finalize(S128(ctx));
    shake128_inc_squeeze(dst, size, S128(ctx));
    ctx->squeezing = 1;
}

void shake128_free(shake128 *ctx)
{
    shake128_inc_ctx_release(S128(ctx));
    memset(ctx, 0, sizeof *ctx);
}

void aes128ctr_init(aes128 *ctx, const uint8_t key[16])
{
    aes128_ecb_keyexp(AESK(ctx), key);
}

static void inc128_be(uint8_t c[16])
{
    for (int i = 15; i >= 0; i--) {
        if (++c[i] != 0) {
            break;
        }
    }
}

void aes128ctr_stream(aes128 *ctx, const uint8_t iv[8], uint8_t *dst, size_t size)
{
    uint8_t ctr[16] = {0};
    uint8_t ks[16];
    memcpy(ctr, iv, 8);
    while (size >= 16) {
        aes128_ecb(dst, ctr, 1, AESK(ctx));
        inc128_be(ctr);
        dst += 16;
        size -= 16;
    }
    if (size > 0) {
        aes128_ecb(ks, ctr, 1, AESK(ctx));
        memcpy(dst, ks, size);
    }
}

void aes128ctr_free(aes128 *ctx)
{
    aes128_ctx_release(AESK(ctx));
    memset(ctx, 0, sizeof *ctx);
}
