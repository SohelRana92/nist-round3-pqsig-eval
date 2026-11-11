/* api.h - NIST signature API over micro-ecc ECDSA P-256 with SHA-256.
 * Public key: 64 bytes (X || Y, uncompressed without 0x04). */
#ifndef PQSIG_ECDSA_API_H
#define PQSIG_ECDSA_API_H
#define CRYPTO_PUBLICKEYBYTES 64
#define CRYPTO_SECRETKEYBYTES 32
#define CRYPTO_BYTES          64
#define CRYPTO_ALGNAME        "ECDSA-P256-SHA256"
int crypto_sign_keypair(unsigned char *pk, unsigned char *sk);
int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk);
int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk);
#endif
