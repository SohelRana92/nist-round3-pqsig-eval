/*
 * harness_rng.h - NIST PQC deterministic random bit generator interface.
 *
 * The declarations match the rng.h that NIST ships with the PQC KAT tools.
 */
#ifndef HARNESS_RNG_H
#define HARNESS_RNG_H

#include <stdio.h>
#include <stddef.h>

/* Length type of randombytes(). Most NIST packages use unsigned long long;
 * a few (MAYO, for example) use size_t. The recipe sets this so the
 * definition matches the scheme's own declaration on 32-bit cores too. */
#ifndef HARNESS_RB_LEN_T
#define HARNESS_RB_LEN_T unsigned long long
#endif

#define RNG_SUCCESS      0
#define RNG_BAD_MAXLEN  -1
#define RNG_BAD_OUTBUF  -2
#define RNG_BAD_REQ_LEN -3

typedef struct {
    unsigned char   buffer[16];
    int             buffer_pos;
    unsigned long   length_remaining;
    unsigned char   key[32];
    unsigned char   ctr[16];
} AES_XOF_struct;

typedef struct {
    unsigned char   Key[32];
    unsigned char   V[16];
    int             reseed_counter;
} AES256_CTR_DRBG_struct;

void AES256_CTR_DRBG_Update(unsigned char *provided_data,
                            unsigned char *Key,
                            unsigned char *V);

int seedexpander_init(AES_XOF_struct *ctx,
                      unsigned char *seed,
                      unsigned char *diversifier,
                      unsigned long maxlen);

int seedexpander(AES_XOF_struct *ctx, unsigned char *x, unsigned long xlen);

void randombytes_init(unsigned char *entropy_input,
                      unsigned char *personalization_string,
                      int security_strength);

int randombytes(unsigned char *x, HARNESS_RB_LEN_T xlen);

/* Harness-only entry points with names no package uses. The driver calls
 * these, so a package header that turns randombytes into a macro cannot
 * redirect the harness's own message and seed generation. */
void harness_drbg_init(const unsigned char entropy[48]);
void harness_drbg_bytes(unsigned char *x, size_t n);

#endif /* HARNESS_RNG_H */
