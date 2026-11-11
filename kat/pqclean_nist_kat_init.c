/* pqclean_nist_kat_init.c - lets PQClean's test/crypto_sign/nistkat.c run
 * on the harness DRBG, so its output can be hashed and compared with the
 * nistkat-sha256 value in the scheme's META.yml. */
#include <stdint.h>
void randombytes_init(unsigned char *entropy_input,
                      unsigned char *personalization_string,
                      int security_strength);
void nist_kat_init(uint8_t *entropy_input, const uint8_t *personalization_string,
                   int security_strength)
{
    randombytes_init(entropy_input, (unsigned char *)personalization_string,
                     security_strength);
}
