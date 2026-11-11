/* fndsa_api.c - NIST API wrapper for c-fn-dsa. Key generation and
 * signing take their seeds from the harness DRBG (32 and 40 bytes), so
 * runs are reproducible and no OS random source is needed. */
#include <string.h>
#include "api.h"

int randombytes(unsigned char *x, unsigned long long xlen);

int crypto_sign_keypair(unsigned char *pk, unsigned char *sk)
{
    unsigned char seed[32];
    randombytes(seed, sizeof seed);
    fndsa_keygen_seeded(PQSIG_FNDSA_LOGN, seed, sizeof seed, sk, pk);
    return 0;
}

int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk)
{
    unsigned char seed[40];
    size_t sig_sz = CRYPTO_BYTES;
    randombytes(seed, sizeof seed);
    memmove(sm + sig_sz, m, (size_t)mlen);
    size_t r = fndsa_sign_seeded(sk, CRYPTO_SECRETKEYBYTES, NULL, 0,
                                 FNDSA_HASH_ID_RAW, sm + sig_sz, (size_t)mlen,
                                 seed, sizeof seed, sm, sig_sz);
    if (r != sig_sz) {
        return -1;
    }
    *smlen = sig_sz + mlen;
    return 0;
}

int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk)
{
    size_t sig_sz = CRYPTO_BYTES;
    if (smlen < sig_sz) {
        return -1;
    }
    size_t ml = (size_t)(smlen - sig_sz);
    if (fndsa_verify(sm, sig_sz, pk, CRYPTO_PUBLICKEYBYTES, NULL, 0,
                     FNDSA_HASH_ID_RAW, sm + sig_sz, ml) != 1) {
        return -1;
    }
    memmove(m, sm + sig_sz, ml);
    *mlen = ml;
    return 0;
}
