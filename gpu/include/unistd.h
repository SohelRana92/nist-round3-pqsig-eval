#ifndef PQG_UNISTD_H
#define PQG_UNISTD_H
#include <stddef.h>
typedef long ssize_t;
ssize_t read(int fd, void *p, size_t n);
int close(int fd);
#endif
