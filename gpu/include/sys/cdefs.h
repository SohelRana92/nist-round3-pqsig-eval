#ifndef PQG_SYS_CDEFS_H
#define PQG_SYS_CDEFS_H
/* glibc's <sys/cdefs.h> macros that packages use without including it. */
#ifndef __always_inline
#define __always_inline __inline __attribute__((__always_inline__))
#endif
#ifndef __attribute_noinline__
#define __attribute_noinline__ __attribute__((__noinline__))
#endif
#ifndef __THROW
#define __THROW
#endif
#endif
