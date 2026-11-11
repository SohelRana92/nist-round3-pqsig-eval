/*
 * plat_linux.c - platform layer for Raspberry Pi 5 and the Ryzen 9 9950X.
 *
 * Cycles come from perf_event_open (PERF_COUNT_HW_CPU_CYCLES, user space
 * only). If perf is not allowed, the harness falls back to CLOCK_MONOTONIC
 * and names the timer "monotonic_ns" so the CSV shows it.
 *
 * Stack use is measured by running the operation in a thread whose stack
 * is painted with a known byte first.
 *
 * The energy marker is a GPIO line driven through the Linux GPIO character
 * device (libgpiod is not needed). Set HARNESS_MARKER_CHIP and
 * HARNESS_MARKER_LINE in the environment, for example
 *   HARNESS_MARKER_CHIP=/dev/gpiochip0 HARNESS_MARKER_LINE=17
 * Without them, the marker is a no-op and the logger uses the ENERGY lines.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <linux/perf_event.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#include "harness.h"

static int g_perf_fd = -1;
static int g_gpio_fd = -1;

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static void open_perf(void)
{
    struct perf_event_attr pe;
    memset(&pe, 0, sizeof pe);
    pe.type = PERF_TYPE_HARDWARE;
    pe.size = sizeof pe;
    pe.config = PERF_COUNT_HW_CPU_CYCLES;
    pe.disabled = 0;
    pe.exclude_kernel = 1;
    pe.exclude_hv = 1;
    g_perf_fd = (int)syscall(SYS_perf_event_open, &pe, 0, -1, -1, 0);
}

static void open_marker(void)
{
    const char *chip = getenv("HARNESS_MARKER_CHIP");
    const char *line = getenv("HARNESS_MARKER_LINE");
    if (!chip || !line) {
        return;
    }
    int cfd = open(chip, O_RDONLY);
    if (cfd < 0) {
        fprintf(stderr, "marker: cannot open %s: %s\n", chip, strerror(errno));
        return;
    }
    struct gpiohandle_request req;
    memset(&req, 0, sizeof req);
    req.lineoffsets[0] = (unsigned)atoi(line);
    req.lines = 1;
    req.flags = GPIOHANDLE_REQUEST_OUTPUT;
    req.default_values[0] = 0;
    strncpy(req.consumer_label, "pqsig-marker", sizeof req.consumer_label - 1);
    if (ioctl(cfd, GPIO_GET_LINEHANDLE_IOCTL, &req) < 0) {
        fprintf(stderr, "marker: cannot claim line %s: %s\n", line, strerror(errno));
        close(cfd);
        return;
    }
    close(cfd);
    g_gpio_fd = req.fd;
}

void plat_init(void)
{
    open_perf();
    open_marker();
}

void plat_stamp(plat_stamp_t *s)
{
    uint64_t c = 0;
    if (g_perf_fd >= 0) {
        if (read(g_perf_fd, &c, sizeof c) != (ssize_t)sizeof c) {
            c = 0;
        }
    }
    s->ns = now_ns();
    s->cycles = (g_perf_fd >= 0) ? c : s->ns;
}

uint64_t plat_cycles_between(const plat_stamp_t *a, const plat_stamp_t *b)
{
    return b->cycles - a->cycles;
}

const char *plat_timer_name(void)
{
    return (g_perf_fd >= 0) ? "perf_cycles" : "monotonic_ns";
}

/* ---------- RAPL package energy (Ryzen 9 9950X) ----------
 * With HARNESS_RAPL set to a powercap energy_uj path (for example
 * /sys/class/powercap/intel-rapl:0/energy_uj, which the amd_energy/RAPL
 * driver also provides on Zen), every marker edge reads the counter.
 * Marker low prints   RAPL,window,<uJ>,<ns>   for the window just ended.
 * Marker high prints  RAPL,idle,<uJ>,<ns>     for the rest just ended.
 * energy/rapl_analyze.py turns these into energy per operation. Reading
 * energy_uj needs root on current kernels (sudo or a udev rule). */
static int g_rapl_init = 0;
static char g_rapl_path[256];
static uint64_t g_rapl_max = 0, g_rapl_e0 = 0, g_rapl_t0 = 0;

static int rapl_read(uint64_t *v)
{
    FILE *f = fopen(g_rapl_path, "r");
    if (!f) {
        return -1;
    }
    unsigned long long x = 0;
    int ok = fscanf(f, "%llu", &x) == 1;
    fclose(f);
    *v = x;
    return ok ? 0 : -1;
}

static uint64_t mono_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

static void rapl_edge(int level)
{
    if (g_rapl_init == 0) {
        const char *p = getenv("HARNESS_RAPL");
        g_rapl_init = -1;
        if (p && *p) {
            snprintf(g_rapl_path, sizeof g_rapl_path, "%s", p);
            char mp[300];
            snprintf(mp, sizeof mp, "%s", g_rapl_path);
            char *slash = strrchr(mp, '/');
            if (slash) {
                snprintf(slash + 1, sizeof mp - (size_t)(slash + 1 - mp), "max_energy_range_uj");
                FILE *f = fopen(mp, "r");
                if (f) {
                    unsigned long long x = 0;
                    if (fscanf(f, "%llu", &x) == 1) {
                        g_rapl_max = x;
                    }
                    fclose(f);
                }
            }
            uint64_t v;
            if (rapl_read(&v) == 0) {
                g_rapl_init = 1;
                g_rapl_e0 = v;
                g_rapl_t0 = mono_ns();
            } else {
                printf("ERROR,rapl_read,%s\n", g_rapl_path);
            }
        }
    }
    if (g_rapl_init != 1) {
        return;
    }
    uint64_t e, t = mono_ns();
    if (rapl_read(&e) != 0) {
        return;
    }
    uint64_t d = (e >= g_rapl_e0) ? e - g_rapl_e0 : e + g_rapl_max - g_rapl_e0;
    printf("RAPL,%s,%llu,%llu\n", level ? "idle" : "window", (unsigned long long)d,
           (unsigned long long)(t - g_rapl_t0));
    fflush(stdout);
    g_rapl_e0 = e;
    g_rapl_t0 = t;
}

/* HARNESS_MARKER_FILE: every marker edge is also written as
 * "CLOCK_MONOTONIC ns,level" to this file, so a logger in another process on
 * the same board (tools/pi_pmic_energy.py reading the Pi 5 PMIC) can tell
 * windows from rests without a wire. */
static FILE *g_mark_file;
static int g_mark_init;

static void mark_file_edge(int level)
{
    if (!g_mark_init) {
        g_mark_init = 1;
        const char *p = getenv("HARNESS_MARKER_FILE");
        if (p && *p) {
            g_mark_file = fopen(p, "a");
        }
    }
    if (g_mark_file) {
        fprintf(g_mark_file, "%llu,%d\n", (unsigned long long)mono_ns(), level ? 1 : 0);
        fflush(g_mark_file);
    }
}

void plat_marker(int level)
{
    rapl_edge(level);
    mark_file_edge(level);
    if (g_gpio_fd < 0) {
        return;
    }
    struct gpiohandle_data d;
    memset(&d, 0, sizeof d);
    d.values[0] = (unsigned char)(level ? 1 : 0);
    ioctl(g_gpio_fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &d);
}

static void sleep_ms(unsigned ms)
{
    struct timespec t = { (time_t)(ms / 1000), (long)(ms % 1000) * 1000000L };
    while (nanosleep(&t, &t) != 0 && errno == EINTR) {
    }
}

void plat_rest_ms(unsigned ms)
{
    if (g_mark_file) {
        sleep_ms(1000); /* settle; the PMIC logger uses the middle of the rest */
    }
    if (g_rapl_init == 1) {
        /* The package needs time to fall back to idle after a busy window
         * (the first RAPL run saw rests that never got below 18-24 W). Let
         * it settle for 1 s, then restart the idle count, so the RAPL,idle
         * row covers only the last ms milliseconds of the rest. */
        sleep_ms(1000);
        uint64_t e;
        if (rapl_read(&e) == 0) {
            g_rapl_e0 = e;
            g_rapl_t0 = mono_ns();
        }
    }
    sleep_ms(ms);
}

void plat_puts(const char *line)
{
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

void *plat_alloc(size_t n)
{
    return malloc(n ? n : 1);
}

void plat_free(void *p)
{
    free(p);
}

/* ---------- painted-stack thread ---------- */

#define PAINT 0xA5u

struct tjob {
    void (*fn)(void *);
    void *arg;
};

static void *thread_main(void *p)
{
    struct tjob *j = (struct tjob *)p;
    j->fn(j->arg);
    return NULL;
}

size_t plat_peak_stack(void (*fn)(void *), void *arg)
{
    size_t mb = 64;
    const char *env = getenv("HARNESS_STACK_MB");
    if (env) {
        mb = (size_t)atoi(env);
    }
    size_t size = mb * 1024 * 1024;
    unsigned char *stk = mmap(NULL, size, PROT_READ | PROT_WRITE,
                              MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (stk == MAP_FAILED) {
        return 0;
    }
    memset(stk, (int)PAINT, size);

    pthread_attr_t at;
    pthread_attr_init(&at);
    pthread_attr_setstack(&at, stk, size);
    struct tjob j = { fn, arg };
    pthread_t t;
    if (pthread_create(&t, &at, thread_main, &j) != 0) {
        munmap(stk, size);
        return 0;
    }
    pthread_join(t, NULL);
    pthread_attr_destroy(&at);

    /* The stack grows down, so the first touched byte from the bottom
     * marks the deepest point. A thread start uses a little stack too;
     * tools/hbuild.py reports a no-op baseline so it can be subtracted. */
    size_t i = 0;
    while (i < size && stk[i] == PAINT) {
        i++;
    }
    size_t used = size - i;
    munmap(stk, size);
    return used;
}

/* ---------- main ---------- */

#ifndef HARNESS_NO_MAIN
int harness_run(int argc, char **argv);

int main(int argc, char **argv)
{
    return harness_run(argc, argv);
}
#endif

