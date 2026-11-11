/* ed25519_rfc8032.c - checks the Ed25519 baseline against RFC 8032,
 * Section 7.1, TEST 1 and TEST 2. */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "monocypher-ed25519.h"

static void unhex(const char *h, uint8_t *o)
{
    for (size_t i = 0; h[2 * i]; i++) {
        sscanf(h + 2 * i, "%2hhx", &o[i]);
    }
}

static int one(const char *name, const char *seed_h, const char *pk_h,
               const char *msg_h, const char *sig_h)
{
    uint8_t seed[32], pk_exp[32], sig_exp[64], msg[64], sk[64], pk[32], sig[64];
    size_t mlen = strlen(msg_h) / 2;
    unhex(seed_h, seed);
    unhex(pk_h, pk_exp);
    unhex(sig_h, sig_exp);
    unhex(msg_h, msg);
    crypto_ed25519_key_pair(sk, pk, seed);
    crypto_ed25519_sign(sig, sk, msg, mlen);
    int ok = memcmp(pk, pk_exp, 32) == 0 && memcmp(sig, sig_exp, 64) == 0 &&
             crypto_ed25519_check(sig, pk, msg, mlen) == 0;
    printf("RFC 8032 %s: %s\n", name, ok ? "pass" : "FAIL");
    return ok ? 0 : 1;
}

int main(void)
{
    int f = 0;
    f |= one("TEST 1",
             "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
             "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
             "",
             "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b");
    f |= one("TEST 2",
             "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
             "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
             "72",
             "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00");
    return f;
}
