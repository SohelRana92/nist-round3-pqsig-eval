/*
 * selftest.c - checks the harness's own AES-256 and SHA-256 against
 * published test vectors before any scheme is measured.
 *   AES-256: FIPS 197, Appendix C.3.
 *   SHA-256: FIPS 180-4 example "abc" and the empty string.
 * Build: gcc -O2 -I../harness/include -I../harness/src selftest.c \
 *            ../harness/src/nist_rng.c ../harness/src/hsha256.c -o selftest
 */
#include <stdio.h>
#include <string.h>
#include "hsha256.h"

void harness_aes256_selftest_block(const unsigned char key[32],
                                   const unsigned char in[16],
                                   unsigned char out[16]);

int main(void)
{
    int fail = 0;
    unsigned char key[32], pt[16], ct[16];
    static const unsigned char expect[16] = {
        0x8e,0xa2,0xb7,0xca,0x51,0x67,0x45,0xbf,0xea,0xfc,0x49,0x90,0x4b,0x49,0x60,0x89
    };
    for (int i = 0; i < 32; i++) {
        key[i] = (unsigned char)i;
    }
    for (int i = 0; i < 16; i++) {
        pt[i] = (unsigned char)(0x11 * i);
    }
    harness_aes256_selftest_block(key, pt, ct);
    if (memcmp(ct, expect, 16) != 0) {
        printf("AES-256 FIPS 197 C.3: FAIL\n");
        fail = 1;
    } else {
        printf("AES-256 FIPS 197 C.3: pass\n");
    }

    char hex[65];
    h_sha256_hex((const unsigned char *)"abc", 3, hex);
    if (strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") != 0) {
        printf("SHA-256 \"abc\": FAIL (%s)\n", hex);
        fail = 1;
    } else {
        printf("SHA-256 \"abc\": pass\n");
    }
    h_sha256_hex((const unsigned char *)"", 0, hex);
    if (strcmp(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") != 0) {
        printf("SHA-256 empty: FAIL (%s)\n", hex);
        fail = 1;
    } else {
        printf("SHA-256 empty: pass\n");
    }
    return fail;
}
