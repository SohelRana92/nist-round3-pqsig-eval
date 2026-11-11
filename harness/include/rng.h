/*
 * rng.h - for packages that include "rng.h" but do not ship one.
 * A package that ships its own rng.h wins, because the builder stages the
 * package's headers first on the include path.
 */
#ifndef rng_h
#define rng_h
#include "harness_rng.h"
#endif
