/*
 * pqclean_randombytes.c - bridges the mupq/PQClean randombytes() interface
 * to the NIST AES-256 CTR_DRBG in nist_rng.c.
 *
 * Packages built in their portable (pqm4/mupq) mode call
 * PQCLEAN_randombytes(uint8_t *, size_t). Packages built in NIST-KAT mode
 * call randombytes(unsigned char *, unsigned long long) directly.
 * Both end up in the same DRBG, so KAT vectors stay reproducible.
 */
#include <stddef.h>
#include <stdint.h>

#ifndef HARNESS_RB_LEN_T
#define HARNESS_RB_LEN_T unsigned long long
#endif
int randombytes(unsigned char *x, HARNESS_RB_LEN_T xlen);

int PQCLEAN_randombytes(uint8_t *output, size_t n)
{
    return randombytes(output, (HARNESS_RB_LEN_T)n);
}
