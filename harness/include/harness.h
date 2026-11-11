/*
 * harness.h - platform interface for the NIST Round-3 signature benchmark.
 *
 * Every platform (Linux on Raspberry Pi 5 and the Ryzen 9 9950X, ESP-IDF on
 * the ESP32, bare-metal MicroBlaze on the Arty S7) implements these hooks in
 * one file under harness/platform/.
 */
#ifndef HARNESS_H
#define HARNESS_H

#include <stddef.h>
#include <stdint.h>

/* Build-time identity of the binary. The builder passes these with -D. */
#ifndef HARNESS_SCHEME
#define HARNESS_SCHEME "unknown"
#endif
#ifndef HARNESS_PARAM
#define HARNESS_PARAM "unknown"
#endif
#ifndef HARNESS_VARIANT
#define HARNESS_VARIANT "ref"
#endif
#ifndef HARNESS_PLATFORM
#define HARNESS_PLATFORM "unknown"
#endif
#ifndef HARNESS_CFLAGS
#define HARNESS_CFLAGS "unknown"
#endif

/* A time stamp holds a cycle count and a wall-clock value in nanoseconds. */
typedef struct {
    uint64_t cycles;
    uint64_t ns;
} plat_stamp_t;

/* Called once before any measurement. */
void plat_init(void);

/* Take a time stamp. */
void plat_stamp(plat_stamp_t *s);

/* Cycles between two stamps. Platforms with a short cycle counter
 * fall back to wall time times the core clock for long intervals. */
uint64_t plat_cycles_between(const plat_stamp_t *a, const plat_stamp_t *b);

/* Name of the cycle source, for the CSV "timer" column. */
const char *plat_timer_name(void);

/* Drive the energy-window marker pin high (1) or low (0). */
void plat_marker(int level);

/* Rest for ms milliseconds between energy windows. Linux sleeps
 * (the core drops to an idle state), the ESP32 blocks the task (the idle
 * task waits for an interrupt), and the MicroBlaze, which has no sleep,
 * busy-waits on its timer. The rest sets the idle level P_idle. */
void plat_rest_ms(unsigned ms);

/* Print one complete output line. The harness adds no newline. */
void plat_puts(const char *line);

/* Run fn(arg) on a painted stack and return the peak stack use in bytes.
 * Returns 0 if the platform cannot measure stack use. */
size_t plat_peak_stack(void (*fn)(void *), void *arg);

/* Allocate a buffer for keys, messages and signatures. */
void *plat_alloc(size_t n);
void plat_free(void *p);

#endif /* HARNESS_H */
