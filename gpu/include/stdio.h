#ifndef PQG_STDIO_H
#define PQG_STDIO_H
#include <stddef.h>
#include "pqg_cdefs.h"
#include <stdarg.h>
/* Output is discarded on the GPU. Verification code does not print; these
 * declarations only let files that also hold test or debug code compile. */
typedef struct pqg_file FILE;
extern FILE *stdin, *stdout, *stderr;
int printf(const char *fmt, ...);
int fprintf(FILE *f, const char *fmt, ...);
int sprintf(char *s, const char *fmt, ...);
int snprintf(char *s, size_t n, const char *fmt, ...);
int vprintf(const char *fmt, va_list ap);
int vfprintf(FILE *f, const char *fmt, va_list ap);
int puts(const char *s);
int putchar(int c);
int fputs(const char *s, FILE *f);
int fflush(FILE *f);
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *f);
size_t fread(void *p, size_t size, size_t n, FILE *f);
size_t fwrite(const void *p, size_t size, size_t n, FILE *f);
#define EOF (-1)
#endif
