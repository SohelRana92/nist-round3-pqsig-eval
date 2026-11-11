/* api.h - NIST signature API over Monocypher's Ed25519 (RFC 8032,
 * SHA-512). Secret key is Monocypher's 64-byte form (seed || public). */
#ifndef PQSIG_ED25519_API_H
#define PQSIG_ED25519_API_H
#define CRYPTO_PUBLICKEYBYTES 32
#define CRYPTO_SECRETKEYBYTES 64
#define CRYPTO_BYTES          64
#define CRYPTO_ALGNAME        "Ed25519"
int crypto_sign_keypair(unsigned char *pk, unsigned char *sk);
int crypto_sign(unsigned char *sm, unsigned long long *smlen,
                const unsigned char *m, unsigned long long mlen,
                const unsigned char *sk);
int crypto_sign_open(unsigned char *m, unsigned long long *mlen,
                     const unsigned char *sm, unsigned long long smlen,
                     const unsigned char *pk);
#endif
