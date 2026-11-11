#ifndef PQG_MATH_H
#define PQG_MATH_H
/* Signature verification in the studied schemes uses no floating point;
 * FN-DSA uses it only in signing. These map to the compiler builtins. */
#define sqrt(x) __builtin_sqrt(x)
#define fabs(x) __builtin_fabs(x)
#define floor(x) __builtin_floor(x)
#define ceil(x) __builtin_ceil(x)
#define log(x) __builtin_log(x)
#define exp(x) __builtin_exp(x)
#define fma(x, y, z) __builtin_fma(x, y, z)
#define llrint(x) __builtin_llrint(x)
#define INFINITY __builtin_inf()
#define NAN __builtin_nan("")
#endif
