/* hsha256.h - small SHA-256 for KAT digests. Names carry an h_ prefix so
 * they never clash with a scheme's own SHA-2 code. */
#ifndef HSHA256_H
#define HSHA256_H

#include <stddef.h>
#include <stdint.h>

void h_sha256(const unsigned char *in, size_t len, unsigned char out[32]);

/* Write the 64-character lowercase hex digest of in[0..len) into hex[65]. */
void h_sha256_hex(const unsigned char *in, size_t len, char hex[65]);

#endif
