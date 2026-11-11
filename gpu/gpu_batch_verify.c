/*
 * gpu_batch_verify.c - GPU batch verification for RQ4 (CUDA driver API).
 *
 * Usage:
 *   gpu_batch_verify CUBIN DUMP REPS [--label SCHEME,PARAM,VARIANT] [--tpb N]
 *                    [--stack BYTES] [--heap-mb MB] [--chunk N]
 *
 *   CUBIN   build/gpu/<recipe>/pq_verify.cubin from gpu/build_gpu.py
 *   DUMP    batch file written by cpu_batch_verify with BATCH_DUMP=file
 *           (format in the header of gpu/cpu_batch_verify.c)
 *   REPS    timed repetitions of the whole batch
 *   --tpb   threads per block (default 128, lowered to the kernel's limit)
 *   --stack per-thread stack in bytes (CU_LIMIT_STACK_SIZE; default 65536).
 *           tools/run_gpu.py passes the ptxas figure plus a margin.
 *   --heap-mb device heap for malloc() inside the packages (default 1024)
 *   --chunk signatures per kernel launch (default 0 = whole batch). A GPU
 *           that also drives a display has a kernel time limit; smaller
 *           chunks keep each launch under it. Timing covers all launches.
 *
 * One GPU thread verifies one signature with the package's own
 * crypto_sign_open (gpu/kernel.c). The program checks every result against
 * the expected one in the dump: all signatures valid except the one with a
 * flipped byte. A repetition with any wrong accept or reject has all_ok=0
 * and the paper must not use it.
 *
 * Timing: CUDA events around the kernel launches only (column ns of the
 * BATCH row). Host-to-device and device-to-host copies are timed once and
 * reported in the GPU_XFER row. One untimed warm-up pass runs first.
 *
 * Output (same BATCH columns as cpu_batch_verify, device = gpu):
 *   GPU_INFO,...  device name, SM count, kernel time limit, registers,
 *                 local memory per thread, threads per block, limits
 *   BATCH,scheme,param,variant,platform,device,mode,threads,batch,rep,ns,verifies_per_s,all_ok
 *   GPU_XFER,scheme,param,variant,mode,batch,h2d_ns,d2h_ns,h2d_bytes
 *   ERROR,<what>,<CUDA error name>,...   when a step fails (a result for
 *                 the feasibility table: stack limit, memory, launch)
 *
 * Build: gcc -O2 -o gpu_batch_verify gpu_batch_verify.c -I/usr/local/cuda/include -lcuda
 */
#include <cuda.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char g_label[256] = "?,?,?";
static const char *g_mode = "?";
static uint64_t g_n = 0;

static void fail(const char *what, CUresult r)
{
    const char *name = "?";
    cuGetErrorName(r, &name);
    printf("ERROR,%s,%s,%s,%s,%llu\n", what, name, g_label, g_mode, (unsigned long long)g_n);
    fflush(stdout);
    exit(1);
}

#define CK(call, what)                \
    do {                              \
        CUresult r_ = (call);         \
        if (r_ != CUDA_SUCCESS) {     \
            fail(what, r_);           \
        }                             \
    } while (0)

static void *xread(FILE *f, size_t n, const char *what)
{
    void *p = malloc(n ? n : 1);
    if (!p || fread(p, 1, n, f) != n) {
        printf("ERROR,dump_read,%s,%s,%s,%llu\n", what, g_label, g_mode, (unsigned long long)g_n);
        exit(1);
    }
    return p;
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: gpu_batch_verify CUBIN DUMP REPS [--label S,P,V] [--tpb N] [--stack B] [--heap-mb MB] [--chunk N]\n");
        return 2;
    }
    const char *cubin = argv[1], *dump = argv[2];
    int reps = atoi(argv[3]);
    unsigned tpb = 128;
    size_t stack = 65536, heap_mb = 1024;
    uint64_t chunk = 0;
    for (int i = 4; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "--label")) {
            snprintf(g_label, sizeof g_label, "%s", argv[i + 1]);
        } else if (!strcmp(argv[i], "--tpb")) {
            tpb = (unsigned)atoi(argv[i + 1]);
        } else if (!strcmp(argv[i], "--stack")) {
            stack = (size_t)atoll(argv[i + 1]);
        } else if (!strcmp(argv[i], "--heap-mb")) {
            heap_mb = (size_t)atoll(argv[i + 1]);
        } else if (!strcmp(argv[i], "--chunk")) {
            chunk = (uint64_t)atoll(argv[i + 1]);
        } else {
            fprintf(stderr, "unknown option %s\n", argv[i]);
            return 2;
        }
    }

    /* ---- read the dump ---- */
    FILE *f = fopen(dump, "rb");
    if (!f) {
        printf("ERROR,dump_open,%s\n", dump);
        return 1;
    }
    uint64_t hdr[6];
    if (fread(hdr, sizeof hdr, 1, f) != 1) {
        printf("ERROR,dump_read,header\n");
        return 1;
    }
    uint64_t n = hdr[0], mlen = hdr[1], smmax = hdr[2], pklen = hdr[3], distinct = hdr[4];
    g_n = n;
    g_mode = distinct ? "distinct" : "shared";
    uint64_t nkeys = distinct ? n : 1;
    /* Each key and signed message starts on a 16-byte boundary on the GPU:
     * the GPU faults on misaligned word loads, which some packages do
     * through pointer casts that x86 tolerates. */
    uint64_t pkstride = (pklen + 15) & ~(uint64_t)15, smstride = (smmax + 15) & ~(uint64_t)15;
    unsigned char *pkraw = xread(f, (size_t)(nkeys * pklen), "pk");
    unsigned char *pk = calloc((size_t)nkeys, (size_t)pkstride);
    if (!pk) {
        printf("ERROR,host_alloc,%s,%s,%llu\n", g_label, g_mode, (unsigned long long)n);
        return 1;
    }
    for (uint64_t k = 0; k < nkeys; k++) {
        memcpy(pk + k * pkstride, pkraw + k * pklen, (size_t)pklen);
    }
    free(pkraw);
    unsigned char *sm = calloc((size_t)n, (size_t)smstride);
    uint64_t *smlen = malloc((size_t)(n * 8));
    unsigned char *m = malloc((size_t)(n * mlen));
    unsigned char *expect = malloc((size_t)n), *got = malloc((size_t)n);
    if (!sm || !smlen || !m || !expect || !got) {
        printf("ERROR,host_alloc,%s,%s,%llu\n", g_label, g_mode, (unsigned long long)n);
        return 1;
    }
    for (uint64_t i = 0; i < n; i++) {
        if (fread(&smlen[i], 8, 1, f) != 1 || fread(sm + i * smstride, 1, (size_t)smmax, f) != smmax
            || fread(&expect[i], 1, 1, f) != 1 || fread(m + i * mlen, 1, (size_t)mlen, f) != mlen) {
            printf("ERROR,dump_read,record,%llu\n", (unsigned long long)i);
            return 1;
        }
    }
    fclose(f);

    /* ---- device, limits, module ---- */
    CUdevice dev;
    CUcontext ctx;
    CK(cuInit(0), "cuInit");
    CK(cuDeviceGet(&dev, 0), "device");
    CK(cuDevicePrimaryCtxRetain(&ctx, dev), "context");
    CK(cuCtxSetCurrent(ctx), "context");
    char name[128] = "?";
    cuDeviceGetName(name, sizeof name, dev);
    for (char *c = name; *c; c++) {
        if (*c == ',') {
            *c = ' ';
        }
    }
    int sms = 0, timeout = 0;
    cuDeviceGetAttribute(&sms, CU_DEVICE_ATTRIBUTE_MULTIPROCESSOR_COUNT, dev);
    cuDeviceGetAttribute(&timeout, CU_DEVICE_ATTRIBUTE_KERNEL_EXEC_TIMEOUT, dev);
    /* The driver reserves the per-thread stack for every thread the GPU can
     * hold at once, so a large stack can exceed device memory: that failure
     * is reported as a feasibility result. */
    CK(cuCtxSetLimit(CU_LIMIT_STACK_SIZE, stack), "stack_limit");
    /* The heap shares device memory with the stack reservation and the
     * batch, so it is capped at half of what is free after the stack. */
    size_t mfree = 0, mtotal = 0;
    CK(cuMemGetInfo(&mfree, &mtotal), "mem_info");
    if ((heap_mb << 20) > mfree / 2) {
        heap_mb = (mfree / 2) >> 20;
    }
    CK(cuCtxSetLimit(CU_LIMIT_MALLOC_HEAP_SIZE, heap_mb << 20), "heap_limit");
    CUmodule mod;
    CUfunction fn;
    CK(cuModuleLoad(&mod, cubin), "module_load");
    CK(cuModuleGetFunction(&fn, mod, "pq_verify"), "kernel_lookup");
    int regs = 0, local = 0, maxt = 0;
    cuFuncGetAttribute(&regs, CU_FUNC_ATTRIBUTE_NUM_REGS, fn);
    cuFuncGetAttribute(&local, CU_FUNC_ATTRIBUTE_LOCAL_SIZE_BYTES, fn);
    cuFuncGetAttribute(&maxt, CU_FUNC_ATTRIBUTE_MAX_THREADS_PER_BLOCK, fn);
    if (maxt > 0 && tpb > (unsigned)maxt) {
        tpb = (unsigned)maxt;
    }
    printf("GPU_INFO,%s,device,%s,sms,%d,exec_timeout,%d,registers,%d,local_bytes,%d,tpb,%u,stack_limit,%zu,heap_mb,%zu,chunk,%llu,mem_free_mb,%zu,mem_total_mb,%zu\n",
           g_label, name, sms, timeout, regs, local, tpb, stack, heap_mb, (unsigned long long)chunk,
           mfree >> 20, mtotal >> 20);
    fflush(stdout);

    /* ---- device buffers and upload ---- */
    CUdeviceptr dpk, dsm, dsmlen, dm, dmout, dgot;
    CK(cuMemAlloc(&dpk, (size_t)(nkeys * pkstride)), "gpu_alloc_pk");
    CK(cuMemAlloc(&dsm, (size_t)(n * smstride)), "gpu_alloc_sm");
    CK(cuMemAlloc(&dsmlen, (size_t)(n * 8)), "gpu_alloc_smlen");
    CK(cuMemAlloc(&dm, (size_t)(n * mlen)), "gpu_alloc_m");
    CK(cuMemAlloc(&dmout, (size_t)(n * smstride)), "gpu_alloc_mout");
    CK(cuMemAlloc(&dgot, (size_t)n), "gpu_alloc_got");
    CUevent e0, e1;
    CK(cuEventCreate(&e0, CU_EVENT_DEFAULT), "event");
    CK(cuEventCreate(&e1, CU_EVENT_DEFAULT), "event");
    float ms = 0;
    CK(cuEventRecord(e0, 0), "event");
    CK(cuMemcpyHtoD(dpk, pk, (size_t)(nkeys * pkstride)), "h2d");
    CK(cuMemcpyHtoD(dsm, sm, (size_t)(n * smstride)), "h2d");
    CK(cuMemcpyHtoD(dsmlen, smlen, (size_t)(n * 8)), "h2d");
    CK(cuMemcpyHtoD(dm, m, (size_t)(n * mlen)), "h2d");
    CK(cuEventRecord(e1, 0), "event");
    CK(cuEventSynchronize(e1), "event");
    CK(cuEventElapsedTime(&ms, e0, e1), "event");
    double h2d_ns = ms * 1e6;
    uint64_t h2d_bytes = nkeys * pkstride + n * (smstride + 8 + mlen);

    uint64_t pk_stride = distinct ? pkstride : 0;
    uint64_t step = chunk ? chunk : n;
    /* Prime: one verification on one thread before anything else. Some
     * packages fill a global table on their first call (SNOVA's
     * "first_time"); with thousands of threads starting at once, most of
     * them would read the table before it is complete. */
    {
        uint64_t first = 0, count = 1;
        void *args[] = {&dpk, &pk_stride, &dsm, &dsmlen, &smstride, &dm, &mlen, &dmout, &first, &count, &dgot};
        CK(cuLaunchKernel(fn, 1, 1, 1, 1, 1, 1, 0, 0, args, NULL), "launch");
        CK(cuCtxSynchronize(), "kernel");
    }
    printf("BATCH_HDR,scheme,param,variant,platform,device,mode,threads,batch,rep,ns,verifies_per_s,all_ok\n");
    double d2h_ns = 0;
    for (int r = -1; r < reps; r++) { /* r = -1 is the untimed warm-up */
        CK(cuMemsetD8(dgot, 0xFF, (size_t)n), "memset");
        CK(cuEventRecord(e0, 0), "event");
        for (uint64_t first = 0; first < n; first += step) {
            uint64_t count = (n - first < step) ? n - first : step;
            void *args[] = {&dpk, &pk_stride, &dsm, &dsmlen, &smstride, &dm, &mlen, &dmout, &first, &count, &dgot};
            unsigned grid = (unsigned)((count + tpb - 1) / tpb);
            CK(cuLaunchKernel(fn, grid, 1, 1, tpb, 1, 1, 0, 0, args, NULL), "launch");
        }
        CK(cuEventRecord(e1, 0), "event");
        /* A trap, an out-of-range access or the display watchdog shows up here. */
        CK(cuEventSynchronize(e1), "kernel");
        CK(cuEventElapsedTime(&ms, e0, e1), "event");
        double kns = ms * 1e6;
        CK(cuEventRecord(e0, 0), "event");
        CK(cuMemcpyDtoH(got, dgot, (size_t)n), "d2h");
        CK(cuEventRecord(e1, 0), "event");
        CK(cuEventSynchronize(e1), "event");
        CK(cuEventElapsedTime(&ms, e0, e1), "event");
        d2h_ns = ms * 1e6;
        int ok = memcmp(got, expect, (size_t)n) == 0;
        if (!ok && r <= 0) {
            uint64_t bad = 0, first_bad = 0;
            for (uint64_t i = 0; i < n; i++) {
                if (got[i] != expect[i]) {
                    if (!bad) {
                        first_bad = i;
                    }
                    bad++;
                }
            }
            printf("NOTE,wrong_results,%s,%s,%llu,rep,%d,count,%llu,first,%llu,got,%d,expected,%d\n", g_label, g_mode,
                   (unsigned long long)n, r, (unsigned long long)bad, (unsigned long long)first_bad,
                   (int)(signed char)got[first_bad], (int)(signed char)expect[first_bad]);
        }
        if (r < 0 && getenv("GPU_SHOW_GOT") && n <= 256) {
            /* debugging aid: the result of every signature after the warm-up */
            printf("GOT,%s", g_mode);
            for (uint64_t i = 0; i < n; i++) {
                printf(",%d", (int)(signed char)got[i]);
            }
            printf("\n");
        }
        if (r < 0) {
            continue;
        }
        char lab[256];
        snprintf(lab, sizeof lab, "%s", g_label);
        printf("BATCH,%s,gpu,gpu,%s,%u,%llu,%d,%.0f,%.1f,%d\n", lab, g_mode, tpb, (unsigned long long)n, r,
               kns, (double)n / (kns / 1e9), ok);
        fflush(stdout);
    }
    printf("GPU_XFER,%s,%s,%llu,%.0f,%.0f,%llu\n", g_label, g_mode, (unsigned long long)n, h2d_ns, d2h_ns,
           (unsigned long long)h2d_bytes);
    cuModuleUnload(mod);
    cuDevicePrimaryCtxRelease(dev);
    return 0;
}
