#ifndef PQG_TIME_H
#define PQG_TIME_H
#include <stddef.h>
typedef long time_t;
typedef long clock_t;
struct timespec { time_t tv_sec; long tv_nsec; };
#define CLOCKS_PER_SEC 1000000l
clock_t clock(void);
time_t time(time_t *t);
#endif
