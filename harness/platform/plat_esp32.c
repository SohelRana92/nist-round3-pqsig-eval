/*
 * plat_esp32.c - platform layer for ESP32-family chips under ESP-IDF 5.x.
 *
 * Cycles: the core cycle counter (esp_cpu_get_cycle_count) is 32 bits and
 * wraps after about 17.9 s at 240 MHz. For intervals longer than 15 s the
 * harness uses esp_timer (64-bit microseconds) times the core clock, and
 * the timer column then reads "esp_timer_x_mhz".
 *
 * Stack: each measured call runs in a fresh FreeRTOS task with a known
 * stack size; peak use = stack size - high-water mark. ESP-IDF counts
 * stack in bytes.
 *
 * Marker: GPIO HARNESS_MARKER_GPIO (default 4) goes high while an energy
 * window runs. Wire it to the logger's input pin.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_cpu.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_rom_sys.h"
#include "driver/gpio.h"

#include "harness.h"

#ifndef HARNESS_MARKER_GPIO
#define HARNESS_MARKER_GPIO 4
#endif
#ifndef HARNESS_STACK_TASK_BYTES
#define HARNESS_STACK_TASK_BYTES (96 * 1024)
#endif

static uint32_t g_mhz;
static int g_long_interval;

void plat_init(void)
{
    g_mhz = esp_rom_get_cpu_ticks_per_us();
    gpio_reset_pin(HARNESS_MARKER_GPIO);
    gpio_set_direction(HARNESS_MARKER_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(HARNESS_MARKER_GPIO, 0);
}

void plat_stamp(plat_stamp_t *s)
{
    s->cycles = (uint32_t)esp_cpu_get_cycle_count();
    s->ns = (uint64_t)esp_timer_get_time() * 1000ULL;
}

uint64_t plat_cycles_between(const plat_stamp_t *a, const plat_stamp_t *b)
{
    uint64_t ns = b->ns - a->ns;
    if (ns < 15000000000ULL) {
        g_long_interval = 0;
        return (uint32_t)((uint32_t)b->cycles - (uint32_t)a->cycles);
    }
    g_long_interval = 1;
    return ns * g_mhz / 1000ULL;
}

const char *plat_timer_name(void)
{
    return g_long_interval ? "esp_timer_x_mhz" : "ccount";
}

void plat_marker(int level)
{
    gpio_set_level(HARNESS_MARKER_GPIO, level ? 1 : 0);
}

void plat_rest_ms(unsigned ms)
{
    vTaskDelay(pdMS_TO_TICKS(ms));
}

void plat_puts(const char *line)
{
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

void *plat_alloc(size_t n)
{
    void *p = heap_caps_malloc(n ? n : 1, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (p == NULL) {
        p = heap_caps_malloc(n ? n : 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (p != NULL) {
            char line[64];
            snprintf(line, sizeof line, "NOTE,alloc_in_psram,%lu", (unsigned long)n);
            plat_puts(line);
        }
    }
    return p;
}

void plat_free(void *p)
{
    heap_caps_free(p);
}

/* ---------- stack measurement ----------
 * Measured inside the benchmark task itself, so no second task (and no
 * second large stack) is needed: the free part of this task's stack below
 * the current frame is painted, the operation runs, and the deepest
 * overwritten byte gives the peak. The ESP32 stack grows downwards from
 * the top of the region that pxTaskGetStackStart() returns the bottom of.
 * The result counts the operation's frames plus the few bytes of the call
 * itself; the harness subtracts its no-op baseline in summarize.py. */
#define PAINT_BYTE 0xA5u
#define PAINT_MARGIN 256u

static __attribute__((noinline)) size_t paint_and_run(void (*fn)(void *), void *arg)
{
    uint8_t *base = pxTaskGetStackStart(NULL);
    volatile uint8_t here = 0;
    uint8_t *sp = (uint8_t *)&here;
    if (base == NULL || sp <= base + PAINT_MARGIN) {
        return 0;
    }
    size_t room = (size_t)(sp - base) - PAINT_MARGIN;
    for (size_t i = 0; i < room; i++) {
        ((volatile uint8_t *)base)[i] = PAINT_BYTE;
    }
    fn(arg);
    size_t untouched = 0;
    while (untouched < room && ((volatile uint8_t *)base)[untouched] == PAINT_BYTE) {
        untouched++;
    }
    if (untouched == 0) {
        plat_puts("NOTE,stack_paint_exhausted_raise_task_stack");
    }
    return (size_t)(sp - base) - untouched;
}

size_t plat_peak_stack(void (*fn)(void *), void *arg)
{
    return paint_and_run(fn, arg);
}
