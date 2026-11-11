/* api.h - NIST signature API over c-fn-dsa (draft FIPS 206 FN-DSA,
 * raw message, empty context). -DPQSIG_FNDSA_LOGN=9 gives FN-DSA-512. */
#ifndef PQSIG_FNDSA_API_H
#define PQSIG_FNDSA_API_H
#include "fndsa.h"
#ifndef PQSIG_FNDSA_LOGN
#define PQSIG_FNDSA_LOGN 9
#endif
#define CRYPTO_PUBLICKEYBYTES FNDSA_VRFY_KEY_SIZE(PQSIG_FNDSA_LOGN)
#define CRYPTO_SECRETKEYBYTES FNDSA_SIGN_KEY_SIZE(PQSIG_FNDSA_LOGN)
#define CRYPTO_BYTES          FNDSA_SIGNATURE_SIZE(PQSIG_FNDSA_LOGN)
#define CRYPTO_ALGNAME        "FN-DSA"
int crypto_sign_keypair(unsigned char *pk, unsigned char *sk);
int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk);
int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk);
#endif
