/*
 * memcheck_sign.c - secret-dependent branch and memory-index check for
 * crypto_sign under Valgrind memcheck (the "ctgrind" method of A. Langley).
 *
 * The secret key bytes are marked undefined after key generation. Any
 * branch or memory address computed from them makes memcheck report a
 * use of uninitialised data. Run:
 *   valgrind --error-exitcode=42 --track-origins=yes ./ct_memcheck 3 2> vg.log
 * Exit 42 means at least one report; vg.log names the source lines.
 * ct/run_ct.sh turns that into one CT row.
 *
 * A report is a finding to inspect, not a proof of leakage: rejection
 * loops whose outcome is public by design (and declassified in a
 * scheme's own constant-time test build) are reported too.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <valgrind/memcheck.h>

#include "api.h"

#ifndef HARNESS_LEN_T
#define HARNESS_LEN_T unsigned long long
#endif

void harness_drbg_init(const unsigned char entropy[48]);
void harness_drbg_bytes(unsigned char *x, size_t n);

int main(int argc, char **argv)
{
    int runs = (argc > 1) ? atoi(argv[1]) : 3;
    unsigned char e[48];
    for (int i = 0; i < 48; i++) {
        e[i] = (unsigned char)(0x33 ^ i);
    }
    harness_drbg_init(e);
    unsigned char *pk = malloc(CRYPTO_PUBLICKEYBYTES);
    unsigned char *sk = malloc(CRYPTO_SECRETKEYBYTES);
    unsigned char m[32];
    unsigned char *sm = malloc(32 + CRYPTO_BYTES);
    HARNESS_LEN_T smlen;
    crypto_sign_keypair(pk, sk);
    harness_drbg_bytes(m, sizeof m);
    for (int i = 0; i < runs; i++) {
        VALGRIND_MAKE_MEM_UNDEFINED(sk, CRYPTO_SECRETKEYBYTES);
        crypto_sign(sm, &smlen, m, sizeof m, sk);
        /* The signature is output data: declassify before any later use. */
        VALGRIND_MAKE_MEM_DEFINED(sm, smlen);
        VALGRIND_MAKE_MEM_DEFINED(&smlen, sizeof smlen);
    }
    printf("signed %d times\n", runs);
    return 0;
}
