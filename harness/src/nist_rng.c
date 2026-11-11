/*
 * nist_rng.c - AES-256 CTR_DRBG as in the NIST PQC KAT tools, without OpenSSL.
 *
 * The NIST rng.c calls OpenSSL for AES-256 in ECB mode. ESP-IDF and the
 * MicroBlaze BSP have no OpenSSL, so this file carries its own AES-256.
 * The DRBG logic follows the NIST file line for line, so the KAT output
 * of every package stays byte-identical. tools/selftest checks this.
 *
 * This AES uses lookup tables and is not constant-time. It only feeds
 * deterministic test randomness to the schemes under test.
 */
#include <string.h>
#include "harness_rng.h"

/* ---------- AES-256 encryption of one block ---------- */

static const unsigned char sbox[256] = {
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16
};

static unsigned char xtime(unsigned char x)
{
    return (unsigned char)((x << 1) ^ ((x & 0x80) ? 0x1b : 0x00));
}

/* Expand a 32-byte key into 15 round keys of 16 bytes. */
static void aes256_expand(const unsigned char *key, unsigned char rk[240])
{
    unsigned char rcon = 0x01;
    memcpy(rk, key, 32);
    for (int i = 8; i < 60; i++) {
        unsigned char t[4];
        memcpy(t, rk + 4 * (i - 1), 4);
        if (i % 8 == 0) {
            unsigned char u = t[0];
            t[0] = (unsigned char)(sbox[t[1]] ^ rcon);
            t[1] = sbox[t[2]];
            t[2] = sbox[t[3]];
            t[3] = sbox[u];
            rcon = xtime(rcon);
        } else if (i % 8 == 4) {
            for (int j = 0; j < 4; j++) {
                t[j] = sbox[t[j]];
            }
        }
        for (int j = 0; j < 4; j++) {
            rk[4 * i + j] = (unsigned char)(rk[4 * (i - 8) + j] ^ t[j]);
        }
    }
}

static void aes256_encrypt_block(const unsigned char rk[240],
                                 const unsigned char in[16],
                                 unsigned char out[16])
{
    unsigned char s[16];
    for (int i = 0; i < 16; i++) {
        s[i] = (unsigned char)(in[i] ^ rk[i]);
    }
    for (int round = 1; round <= 14; round++) {
        unsigned char t[16];
        /* SubBytes and ShiftRows. State is column-major: s[col*4 + row]. */
        for (int c = 0; c < 4; c++) {
            for (int r = 0; r < 4; r++) {
                t[c * 4 + r] = sbox[s[((c + r) % 4) * 4 + r]];
            }
        }
        /* MixColumns, skipped in the last round. */
        if (round != 14) {
            for (int c = 0; c < 4; c++) {
                unsigned char a0 = t[c * 4 + 0];
                unsigned char a1 = t[c * 4 + 1];
                unsigned char a2 = t[c * 4 + 2];
                unsigned char a3 = t[c * 4 + 3];
                unsigned char all = (unsigned char)(a0 ^ a1 ^ a2 ^ a3);
                t[c * 4 + 0] = (unsigned char)(a0 ^ all ^ xtime((unsigned char)(a0 ^ a1)));
                t[c * 4 + 1] = (unsigned char)(a1 ^ all ^ xtime((unsigned char)(a1 ^ a2)));
                t[c * 4 + 2] = (unsigned char)(a2 ^ all ^ xtime((unsigned char)(a2 ^ a3)));
                t[c * 4 + 3] = (unsigned char)(a3 ^ all ^ xtime((unsigned char)(a3 ^ a0)));
            }
        }
        for (int i = 0; i < 16; i++) {
            s[i] = (unsigned char)(t[i] ^ rk[16 * round + i]);
        }
    }
    memcpy(out, s, 16);
}

/* Same signature as the static helper in the NIST rng.c. */
static void AES256_ECB(unsigned char *key, unsigned char *ctr, unsigned char *buffer)
{
    unsigned char rk[240];
    aes256_expand(key, rk);
    aes256_encrypt_block(rk, ctr, buffer);
}

/* ---------- NIST seed expander ---------- */

int seedexpander_init(AES_XOF_struct *ctx,
                      unsigned char *seed,
                      unsigned char *diversifier,
                      unsigned long maxlen)
{
    if (maxlen >= 0x100000000UL) {
        return RNG_BAD_MAXLEN;
    }
    ctx->length_remaining = maxlen;
    memcpy(ctx->key, seed, 32);
    memcpy(ctx->ctr, diversifier, 8);
    ctx->ctr[11] = (unsigned char)(maxlen % 256);
    maxlen >>= 8;
    ctx->ctr[10] = (unsigned char)(maxlen % 256);
    maxlen >>= 8;
    ctx->ctr[9] = (unsigned char)(maxlen % 256);
    maxlen >>= 8;
    ctx->ctr[8] = (unsigned char)(maxlen % 256);
    memset(ctx->ctr + 12, 0x00, 4);
    ctx->buffer_pos = 16;
    memset(ctx->buffer, 0x00, 16);
    return RNG_SUCCESS;
}

int seedexpander(AES_XOF_struct *ctx, unsigned char *x, unsigned long xlen)
{
    unsigned long offset;

    if (x == NULL) {
        return RNG_BAD_OUTBUF;
    }
    if (xlen >= ctx->length_remaining) {
        return RNG_BAD_REQ_LEN;
    }
    ctx->length_remaining -= xlen;
    offset = 0;
    while (xlen > 0) {
        if (xlen <= (unsigned long)(16 - ctx->buffer_pos)) {
            memcpy(x + offset, ctx->buffer + ctx->buffer_pos, xlen);
            ctx->buffer_pos += (int)xlen;
            return RNG_SUCCESS;
        }
        memcpy(x + offset, ctx->buffer + ctx->buffer_pos, 16 - ctx->buffer_pos);
        xlen -= 16 - ctx->buffer_pos;
        offset += 16 - ctx->buffer_pos;
        AES256_ECB(ctx->key, ctx->ctr, ctx->buffer);
        ctx->buffer_pos = 0;
        for (int i = 15; i >= 12; i--) {
            if (ctx->ctr[i] == 0xff) {
                ctx->ctr[i] = 0x00;
            } else {
                ctx->ctr[i]++;
                break;
            }
        }
    }
    return RNG_SUCCESS;
}

/* ---------- NIST AES-256 CTR_DRBG ---------- */

/* HARNESS_RNG_TLS (set for cpu_batch_verify only) gives every thread its
 * own DRBG state, so the batch inputs can be signed on all cores. Every
 * other program keeps the single shared state of the NIST rng.c. */
#ifdef HARNESS_RNG_TLS
static _Thread_local AES256_CTR_DRBG_struct DRBG_ctx;
#else
static AES256_CTR_DRBG_struct DRBG_ctx;
#endif

void AES256_CTR_DRBG_Update(unsigned char *provided_data,
                            unsigned char *Key,
                            unsigned char *V)
{
    unsigned char temp[48];

    for (int i = 0; i < 3; i++) {
        for (int j = 15; j >= 0; j--) {
            if (V[j] == 0xff) {
                V[j] = 0x00;
            } else {
                V[j]++;
                break;
            }
        }
        AES256_ECB(Key, V, temp + 16 * i);
    }
    if (provided_data != NULL) {
        for (int i = 0; i < 48; i++) {
            temp[i] ^= provided_data[i];
        }
    }
    memcpy(Key, temp, 32);
    memcpy(V, temp + 32, 16);
}

void randombytes_init(unsigned char *entropy_input,
                      unsigned char *personalization_string,
                      int security_strength)
{
    unsigned char seed_material[48];

    (void)security_strength;
    memcpy(seed_material, entropy_input, 48);
    if (personalization_string != NULL) {
        for (int i = 0; i < 48; i++) {
            seed_material[i] ^= personalization_string[i];
        }
    }
    memset(DRBG_ctx.Key, 0x00, 32);
    memset(DRBG_ctx.V, 0x00, 16);
    AES256_CTR_DRBG_Update(seed_material, DRBG_ctx.Key, DRBG_ctx.V);
    DRBG_ctx.reseed_counter = 1;
}

int randombytes(unsigned char *x, HARNESS_RB_LEN_T xlen)
{
    unsigned char block[16];
    HARNESS_RB_LEN_T i = 0;

    while (xlen > 0) {
        for (int j = 15; j >= 0; j--) {
            if (DRBG_ctx.V[j] == 0xff) {
                DRBG_ctx.V[j] = 0x00;
            } else {
                DRBG_ctx.V[j]++;
                break;
            }
        }
        AES256_ECB(DRBG_ctx.Key, DRBG_ctx.V, block);
        if (xlen > 15) {
            memcpy(x + i, block, 16);
            i += 16;
            xlen -= 16;
        } else {
            memcpy(x + i, block, (size_t)xlen);
            xlen = 0;
        }
    }
    AES256_CTR_DRBG_Update(NULL, DRBG_ctx.Key, DRBG_ctx.V);
    DRBG_ctx.reseed_counter++;
    return RNG_SUCCESS;
}

void harness_drbg_init(const unsigned char entropy[48])
{
    unsigned char e[48];
    memcpy(e, entropy, 48);
    randombytes_init(e, NULL, 256);
}

void harness_drbg_bytes(unsigned char *x, size_t n)
{
    randombytes(x, (HARNESS_RB_LEN_T)n);
}

/* Exposed for tools/selftest only. */
void harness_aes256_selftest_block(const unsigned char key[32],
                                   const unsigned char in[16],
                                   unsigned char out[16])
{
    unsigned char rk[240];
    aes256_expand(key, rk);
    aes256_encrypt_block(rk, in, out);
}
