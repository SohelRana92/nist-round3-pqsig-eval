/* api.h - NIST signature API over slhdsa-c (FIPS 205 SLH-DSA, pure mode,
 * empty context string). The recipe selects the set with
 * -DPQSIG_SLH_PARAM=slh_dsa_sha2_128s (or _128f). */
#ifndef PQSIG_SLHDSA_API_H
#define PQSIG_SLHDSA_API_H
#include <stddef.h>
#include "slh_dsa.h"
#ifndef PQSIG_SLH_PARAM
#error "set PQSIG_SLH_PARAM"
#endif
#define CRYPTO_PUBLICKEYBYTES slh_pk_sz(&PQSIG_SLH_PARAM)
#define CRYPTO_SECRETKEYBYTES slh_sk_sz(&PQSIG_SLH_PARAM)
#define CRYPTO_BYTES          slh_sig_sz(&PQSIG_SLH_PARAM)
#define CRYPTO_ALGNAME        slh_alg_id(&PQSIG_SLH_PARAM)
int crypto_sign_keypair(unsigned char *pk, unsigned char *sk);
int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk);
int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk);
#endif
