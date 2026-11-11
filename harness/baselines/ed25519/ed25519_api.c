/* ed25519_api.c - NIST API wrapper for Monocypher Ed25519. */
#include <string.h>
#include <stdint.h>
#include "api.h"
#include "monocypher-ed25519.h"

int randombytes(unsigned char *x, unsigned long long xlen);

int crypto_sign_keypair(unsigned char *pk, unsigned char *sk)
{
    uint8_t seed[32];
    randombytes(seed, sizeof seed);
    crypto_ed25519_key_pair(sk, pk, seed);   /* wipes seed */
    return 0;
}

int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk)
{
    memmove(sm + 64, m, (size_t)mlen);
    crypto_ed25519_sign(sm, sk, sm + 64, (size_t)mlen);
    *smlen = 64 + mlen;
    return 0;
}

int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk)
{
    if (smlen < 64) {
        return -1;
    }
    size_t ml = (size_t)(smlen - 64);
    if (crypto_ed25519_check(sm, pk, sm + 64, ml) != 0) {
        return -1;
    }
    memmove(m, sm + 64, ml);
    *mlen = ml;
    return 0;
}
