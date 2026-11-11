/*
 * aes-publicinputs.h - pqsig-eval compatibility header for the UOV
 * (pqov) portable path (_UTILS_PQM4_).
 *
 * pqov expects pqm4's aes128_ctr_publicinputs(out, outlen, nonce, ctr, ctx),
 * where the 16-byte counter block is a 12-byte nonce followed by a 32-bit
 * big-endian counter. This header builds that call from the portable
 * PQClean AES-128 ECB in harness/common/aes.c. The construction follows
 * the wrapper in mupq/crypto_sign/ov-Ip/ref/utils_prng.c. KAT equality
 * with the official OpenSSL build (tools/run_kat_compare.sh) checks it.
 *
 * This header sits before harness/common on the include path only for
 * UOV recipes.
 */
#ifndef PQSIG_UOV_AES_PUBLICINPUTS_H
#define PQSIG_UOV_AES_PUBLICINPUTS_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "aes.h"

typedef aes128ctx aes128ctx_publicinputs;

static inline void aes128_ctr_keyexp_publicinputs(aes128ctx_publicinputs *r,
                                                  const unsigned char *key)
{
    aes128_ecb_keyexp(r, key);
}

static inline void pqsig_inc_be32(unsigned char *p)
{
    for (int i = 3; i >= 0; i--) {
        if (++p[i] != 0) {
            break;
        }
    }
}

static inline void aes128_ctr_publicinputs(unsigned char *out, size_t outlen,
                                           const unsigned char *nonce,
                                           uint32_t ctr,
                                           const aes128ctx_publicinputs *ctx)
{
    unsigned char blk[16];
    unsigned char tmp[16];
    memcpy(blk, nonce, 12);
    blk[12] = (unsigned char)(ctr >> 24);
    blk[13] = (unsigned char)(ctr >> 16);
    blk[14] = (unsigned char)(ctr >> 8);
    blk[15] = (unsigned char)ctr;
    while (outlen >= 16) {
        aes128_ecb(out, blk, 1, ctx);
        out += 16;
        outlen -= 16;
        pqsig_inc_be32(blk + 12);
    }
    if (outlen > 0) {
        aes128_ecb(tmp, blk, 1, ctx);
        memcpy(out, tmp, outlen);
    }
}

#endif
