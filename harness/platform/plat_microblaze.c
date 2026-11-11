/*
 * plat_microblaze.c - bare-metal platform layer for one MicroBlaze on the
 * Digilent Arty S7, built with Vitis (standalone BSP).
 *
 * Hardware expected in the block design (fpga/build_mb.tcl makes it):
 *   AXI Timer  (axi_timer_0) clocked at the CPU clock, used in cascade
 *              mode as one 64-bit up-counter, so ticks = CPU cycles.
 *   AXI GPIO   (axi_gpio_0) channel 1 bit 0 = energy marker, on a Pmod pin.
 *   AXI UART Lite at 115200 baud for output (stdout).
 *   DDR3 through MIG for keys, heap and stack.
 *
 * Addresses come from xparameters.h, whose macro names differ between
 * Vitis releases (classic and system-device-tree flows). fpga/mb_run.py
 * reads the generated xparameters.h and passes PQ_TMR_BASE, PQ_GPIO_BASE
 * and PQ_CPU_HZ, which take precedence; the fallbacks below cover a
 * hand-made Vitis application.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "xparameters.h"
#include "xil_io.h"
#include "xil_cache.h"

#include "harness.h"

/* AXI Timer register map (PG079): two counters, 0x10 apart. */
#if defined(PQ_TMR_BASE)
#define TMR_BASE PQ_TMR_BASE
#elif defined(XPAR_AXI_TIMER_0_BASEADDR)
#define TMR_BASE XPAR_AXI_TIMER_0_BASEADDR
#elif defined(XPAR_TMRCTR_0_BASEADDR)
#define TMR_BASE XPAR_TMRCTR_0_BASEADDR
#else
#error "no AXI Timer in xparameters.h"
#endif
#define TCSR0 0x00
#define TLR0  0x04
#define TCR0  0x08
#define TCSR1 0x10
#define TLR1  0x14
#define TCR1  0x18
/* TCSR bits */
#define T_LOAD   (1u << 5)
#define T_ENT    (1u << 7)
#define T_CASC   (1u << 11)

#if defined(PQ_GPIO_BASE)
#define GPIO_BASE PQ_GPIO_BASE
#elif defined(XPAR_AXI_GPIO_0_BASEADDR)
#define GPIO_BASE XPAR_AXI_GPIO_0_BASEADDR
#elif defined(XPAR_GPIO_0_BASEADDR)
#define GPIO_BASE XPAR_GPIO_0_BASEADDR
#endif

#if defined(PQ_CPU_HZ)
#define CPU_HZ PQ_CPU_HZ
#elif defined(XPAR_CPU_CORE_CLOCK_FREQ_HZ)
#define CPU_HZ XPAR_CPU_CORE_CLOCK_FREQ_HZ
#elif defined(XPAR_MICROBLAZE_CORE_CLOCK_FREQ_HZ)
#define CPU_HZ XPAR_MICROBLAZE_CORE_CLOCK_FREQ_HZ
#else
#define CPU_HZ 81247969u   /* MIG ui_clk of fpga/build_mb.tcl */
#endif

static uint64_t ticks64(void)
{
    uint32_t hi, lo, hi2;
    do {
        hi = Xil_In32(TMR_BASE + TCR1);
        lo = Xil_In32(TMR_BASE + TCR0);
        hi2 = Xil_In32(TMR_BASE + TCR1);
    } while (hi != hi2);
    return ((uint64_t)hi << 32) | lo;
}

void plat_init(void)
{
    static int checked = 0;
    Xil_ICacheEnable();
    Xil_DCacheEnable();
    /* Cascade mode (PG079): both counters stop, both load registers are
       written and loaded, then every LOAD bit is cleared again. A LOAD bit
       left set holds its counter at the load value: the first version of
       this file left LOAD1 set, so the high word stayed 0 and the count
       wrapped every 2^32 cycles (52.9 s at 81.25 MHz).
       The low word starts 4096 counts below its wrap, so the check below
       sees the carry into the high word within microseconds. */
    Xil_Out32(TMR_BASE + TCSR0, 0);
    Xil_Out32(TMR_BASE + TCSR1, 0);
    Xil_Out32(TMR_BASE + TLR0, 0xFFFFF000u);
    Xil_Out32(TMR_BASE + TLR1, 0);
    Xil_Out32(TMR_BASE + TCSR0, T_LOAD | T_CASC);
    Xil_Out32(TMR_BASE + TCSR1, T_LOAD);
    Xil_Out32(TMR_BASE + TCSR1, 0);
    Xil_Out32(TMR_BASE + TCSR0, T_CASC);
    Xil_Out32(TMR_BASE + TCSR0, T_ENT | T_CASC);
    if (!checked) {
        checked = 1;
        uint32_t guard = 0;
        while (Xil_In32(TMR_BASE + TCR0) >= 0x80000000u && guard < 10000000u) {
            guard++;
        }
        uint32_t hi = Xil_In32(TMR_BASE + TCR1);
        if (hi == 1u) {
            plat_puts("NOTE,timer64_carry_ok");
        } else {
            char b[80];
            snprintf(b, sizeof b, "ERROR,timer64_carry_failed,high_word,%lu", (unsigned long)hi);
            plat_puts(b);
        }
    }
#ifdef GPIO_BASE
    Xil_Out32(GPIO_BASE + 0x4, 0);   /* channel 1 direction: output */
    Xil_Out32(GPIO_BASE + 0x0, 0);
#endif
}

void plat_stamp(plat_stamp_t *s)
{
    /* The clock is not a divisor of 1 GHz (81.25 MHz), so split the
       conversion to keep it exact without overflowing 64 bits. */
    uint64_t c = ticks64();
    s->cycles = c;
    s->ns = (c / CPU_HZ) * 1000000000ULL + ((c % CPU_HZ) * 1000000000ULL) / CPU_HZ;
}

uint64_t plat_cycles_between(const plat_stamp_t *a, const plat_stamp_t *b)
{
    return b->cycles - a->cycles;
}

const char *plat_timer_name(void)
{
    return "axi_timer64";
}

void plat_marker(int level)
{
#ifdef GPIO_BASE
    Xil_Out32(GPIO_BASE + 0x0, level ? 1u : 0u);
#else
    (void)level;
#endif
}

void plat_rest_ms(unsigned ms)
{
    /* No sleep state on this soft core: busy-wait on the AXI timer. */
    plat_stamp_t a, b;
    plat_stamp(&a);
    do {
        plat_stamp(&b);
    } while (b.ns - a.ns < (uint64_t)ms * 1000000ULL);
}

void plat_puts(const char *line)
{
    fputs(line, stdout);
    fputs("\r\n", stdout);
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

/* ---------- stack painting ----------
 * The Vitis linker script defines _stack_end (lowest address) and _stack
 * (highest). We paint from _stack_end up to just below the current stack
 * pointer, run fn, then find the deepest touched byte. */
extern char _stack_end[];

#define PAINT 0xA5u

static inline uintptr_t current_sp(void)
{
    uintptr_t sp;
    __asm__ volatile("addik %0, r1, 0" : "=r"(sp));
    return sp;
}

size_t plat_peak_stack(void (*fn)(void *), void *arg)
{
    uint8_t *lo = (uint8_t *)_stack_end;
    uint8_t *top = (uint8_t *)(current_sp() - 256);
    if (top <= lo) {
        return 0;
    }
    memset(lo, PAINT, (size_t)(top - lo));
    fn(arg);
    uint8_t *p = lo;
    while (p < top && *p == PAINT) {
        p++;
    }
    return (size_t)(top - p);
}
