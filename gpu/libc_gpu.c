/*
 * libc_gpu.c - the few C library functions the packages call, for the GPU.
 *
 * Compiled with clang --target=nvptx64-nvidia-cuda to LLVM bitcode and
 * linked with each scheme by gpu/build_gpu.py. Everything that the
 * verification path does not reach is removed by the optimiser, so most
 * of these functions vanish from the final kernel.
 *
 * malloc and free are not defined here: they are PTX system calls that the
 * CUDA driver resolves to its device heap.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>

void *malloc(size_t n);
void free(void *p);

void *memcpy(void *restrict d, const void *restrict s, size_t n)
{
    unsigned char *dp = d;
    const unsigned char *sp = s;
    while (n--) {
        *dp++ = *sp++;
    }
    return d;
}

void *memmove(void *d, const void *s, size_t n)
{
    unsigned char *dp = d;
    const unsigned char *sp = s;
    if (dp < sp) {
        while (n--) {
            *dp++ = *sp++;
        }
    } else {
        while (n--) {
            dp[n] = sp[n];
        }
    }
    return d;
}

void *memset(void *d, int c, size_t n)
{
    unsigned char *dp = d;
    while (n--) {
        *dp++ = (unsigned char)c;
    }
    return d;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *x = a, *y = b;
    for (size_t i = 0; i < n; i++) {
        if (x[i] != y[i]) {
            return (int)x[i] - (int)y[i];
        }
    }
    return 0;
}

void *memchr(const void *s, int c, size_t n)
{
    const unsigned char *p = s;
    for (size_t i = 0; i < n; i++) {
        if (p[i] == (unsigned char)c) {
            return (void *)(p + i);
        }
    }
    return NULL;
}

size_t strlen(const char *s)
{
    size_t n = 0;
    while (s[n]) {
        n++;
    }
    return n;
}

int strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return (int)(unsigned char)*a - (int)(unsigned char)*b;
}

int strncmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++) {
        if (*a != *b || !*a) {
            return (int)(unsigned char)*a - (int)(unsigned char)*b;
        }
    }
    return 0;
}

char *strcpy(char *restrict d, const char *restrict s)
{
    char *r = d;
    while ((*d++ = *s++)) {
    }
    return r;
}

char *strncpy(char *restrict d, const char *restrict s, size_t n)
{
    size_t i = 0;
    for (; i < n && s[i]; i++) {
        d[i] = s[i];
    }
    for (; i < n; i++) {
        d[i] = 0;
    }
    return d;
}

void *calloc(size_t n, size_t size)
{
    if (size && n > SIZE_MAX / size) {
        return NULL;
    }
    void *p = malloc(n * size);
    if (p) {
        memset(p, 0, n * size);
    }
    return p;
}

/* The device heap has no usable-size query, so realloc cannot be done
 * safely. No verification routine in the study calls it. */
void *realloc(void *p, size_t n)
{
    (void)p;
    (void)n;
    __builtin_trap();
    return NULL;
}

/* The CUDA device heap returns 16-byte aligned blocks. Larger alignments
 * are served by over-allocating; the original pointer is not kept, so such
 * blocks are never freed (a small leak per call, acceptable for one batch). */
void *aligned_alloc(size_t align, size_t n)
{
    if (align <= 16) {
        return malloc(n);
    }
    unsigned char *p = malloc(n + align);
    if (!p) {
        return NULL;
    }
    uintptr_t a = ((uintptr_t)p + align - 1) & ~(uintptr_t)(align - 1);
    return (void *)a;
}

int posix_memalign(void **out, size_t align, size_t n)
{
    void *p = aligned_alloc(align, n);
    if (!p) {
        return 12;
    }
    *out = p;
    return 0;
}

_Noreturn void abort(void)
{
    __builtin_trap();
    __builtin_unreachable();
}

_Noreturn void exit(int status)
{
    (void)status;
    __builtin_trap();
    __builtin_unreachable();
}

int abs(int x) { return x < 0 ? -x : x; }
long labs(long x) { return x < 0 ? -x : x; }
long long llabs(long long x) { return x < 0 ? -x : x; }

int errno;

/* Printing is discarded on the device. */
typedef struct pqg_file FILE;
FILE *stdin, *stdout, *stderr;
int printf(const char *fmt, ...) { (void)fmt; return 0; }
int fprintf(FILE *f, const char *fmt, ...) { (void)f; (void)fmt; return 0; }
int vprintf(const char *fmt, va_list ap) { (void)fmt; (void)ap; return 0; }
int vfprintf(FILE *f, const char *fmt, va_list ap) { (void)f; (void)fmt; (void)ap; return 0; }
int puts(const char *s) { (void)s; return 0; }
int putchar(int c) { return c; }
int fputs(const char *s, FILE *f) { (void)s; (void)f; return 0; }
int fflush(FILE *f) { (void)f; return 0; }
