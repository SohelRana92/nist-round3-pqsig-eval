#ifndef PQG_ASSERT_H
#define PQG_ASSERT_H
/* Release builds of the packages define NDEBUG; without it a failed
 * assertion stops the thread with a trap, as abort() does on a CPU. */
#ifdef NDEBUG
#define assert(x) ((void)0)
#else
#define assert(x) ((x) ? (void)0 : __builtin_trap())
#endif
#ifndef static_assert
#define static_assert _Static_assert
#endif
#endif
