/* ecdsa_dump.c - signs three messages with the ECDSA P-256 baseline and
 * prints pk, message and signature in hex. ecdsa_crosscheck.py verifies
 * them with the Python "cryptography" package (OpenSSL), an independent
 * implementation. */
#include <stdio.h>
#include <string.h>
#include "api.h"
void harness_drbg_init(const unsigned char entropy[48]);

static void hex(const unsigned char *p, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        printf("%02x", p[i]);
    }
}

int main(void)
{
    unsigned char e[48], pk[CRYPTO_PUBLICKEYBYTES], sk[CRYPTO_SECRETKEYBYTES];
    unsigned char sm[64 + 64];
    unsigned long long smlen;
    for (int i = 0; i < 48; i++) {
        e[i] = (unsigned char)(3 * i);
    }
    harness_drbg_init(e);
    crypto_sign_keypair(pk, sk);
    const char *msgs[3] = { "abc", "", "post-quantum benchmark harness" };
    for (int k = 0; k < 3; k++) {
        size_t ml = strlen(msgs[k]);
        crypto_sign(sm, &smlen, (const unsigned char *)msgs[k], ml, sk);
        hex(pk, 64); printf(" ");
        hex((const unsigned char *)msgs[k], ml); printf(" ");
        hex(sm, 64); printf("\n");
    }
    return 0;
}
