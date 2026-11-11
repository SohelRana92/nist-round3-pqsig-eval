#ifndef PQG_STDLIB_H
#define PQG_STDLIB_H
#include <stddef.h>
#include "pqg_cdefs.h"
/* malloc and free are PTX system calls; the CUDA driver provides them
 * from the device heap (size set with CU_LIMIT_MALLOC_HEAP_SIZE). */
void *malloc(size_t n);
void free(void *p);
void *calloc(size_t n, size_t size);
void *realloc(void *p, size_t n);
void *aligned_alloc(size_t align, size_t n);
int posix_memalign(void **p, size_t align, size_t n);
_Noreturn void abort(void);
_Noreturn void exit(int status);
int abs(int x);
long labs(long x);
long long llabs(long long x);
int atoi(const char *s);
#define EXIT_SUCCESS 0
#define EXIT_FAILURE 1
#endif
