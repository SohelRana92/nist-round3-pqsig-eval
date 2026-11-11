/* ecdsa_api.c - NIST API wrapper for micro-ecc ECDSA P-256.
 * The nonce generator is the harness DRBG through uECC_set_rng, so
 * signatures are randomized (FIPS 186-5 ECDSA) but reproducible. */
#include <string.h>
#include <stdint.h>
#include "api.h"
#include "uECC.h"
#include "hsha256.h"

int randombytes(unsigned char *x, unsigned long long xlen);

static int rng(uint8_t *dest, unsigned size)
{
    randombytes(dest, size);
    return 1;
}

static void setup(void)
{
    uECC_set_rng(rng);
}

int crypto_sign_keypair(unsigned char *pk, unsigned char *sk)
{
    setup();
    return uECC_make_key(pk, sk, uECC_secp256r1()) == 1 ? 0 : -1;
}

int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk)
{
    unsigned char h[32];
    setup();
    memmove(sm + 64, m, (size_t)mlen);
    h_sha256(sm + 64, (size_t)mlen, h);
    if (uECC_sign(sk, h, 32, sm, uECC_secp256r1()) != 1) {
        return -1;
    }
    *smlen = 64 + mlen;
    return 0;
}

int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk)
{
    unsigned char h[32];
    if (smlen < 64) {
        return -1;
    }
    size_t ml = (size_t)(smlen - 64);
    h_sha256(sm + 64, ml, h);
    if (uECC_verify(pk, h, 32, sm, uECC_secp256r1()) != 1) {
        return -1;
    }
    memmove(m, sm + 64, ml);
    *mlen = ml;
    return 0;
}
