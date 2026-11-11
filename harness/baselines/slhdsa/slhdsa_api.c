/* slhdsa_api.c - NIST API wrapper for slhdsa-c. Signed message is
 * signature || message. Signing is hedged: addrnd comes from the
 * harness DRBG, as FIPS 205 recommends. */
#include <string.h>
#include <stdint.h>
#include "api.h"

int randombytes(unsigned char *x, unsigned long long xlen);

static int rbg(uint8_t *x, size_t xlen)
{
    return randombytes(x, (unsigned long long)xlen);
}

int crypto_sign_keypair(unsigned char *pk, unsigned char *sk)
{
    return slh_keygen(sk, pk, rbg, &PQSIG_SLH_PARAM);
}

int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk)
{
    uint8_t addrnd[32];
    size_t n = slh_pk_sz(&PQSIG_SLH_PARAM) / 2;   /* n bytes of randomness */
    size_t sig_sz = slh_sig_sz(&PQSIG_SLH_PARAM);
    randombytes(addrnd, n);
    memmove(sm + sig_sz, m, (size_t)mlen);
    size_t r = slh_sign(sm, sm + sig_sz, (size_t)mlen, NULL, 0, sk, addrnd,
                        &PQSIG_SLH_PARAM);
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
    size_t sig_sz = slh_sig_sz(&PQSIG_SLH_PARAM);
    if (smlen < sig_sz) {
        return -1;
    }
    size_t ml = (size_t)(smlen - sig_sz);
    if (slh_verify(sm + sig_sz, ml, sm, sig_sz, NULL, 0, pk, &PQSIG_SLH_PARAM) != 1) {
        return -1;
    }
    memmove(m, sm + sig_sz, ml);
    *mlen = ml;
    return 0;
}
