# GPU batch verification

One GPU thread verifies one signature. The thread runs the package's own
`crypto_sign_open`, compiled from the same portable C sources that run on
the ESP32. This is a direct port, not a GPU-optimised implementation: it
shows how far the submitted code goes on a GPU without rewriting, and
the batch table says so.

## How the kernel is built

```
recipe sources ──hbuild --platform gpu──► host objects + NVPTX bitcode (.o.nvbc)
                  (gpu/cc_gpu.py wraps the compiler, also inside make and CMake)
libscheme.a members, harness helpers, gpu/libc_gpu.c, gpu/kernel.c
  ──llvm-link (archive rules)──► opt -O3, everything internal but pq_verify
  ──llc──► PTX (sm_89 PTX) ──ptxas -arch=sm_120──► pq_verify.cubin
```

* Plain C goes to the GPU through clang's NVPTX target, so the C code is
  not rewritten as CUDA C++.
* `gpu/include/` is a minimal C library for the device. `malloc` and `free`
  are PTX system calls that use the CUDA device heap.
* `ptxas -v` reports registers and the cumulative stack per thread;
  `build/gpu/<recipe>/gpu_build.json` keeps both.
* Only portable recipes are built: ref, ref-portable, opt-portable, SNOVA
  opt, mem and tiny. AVX2 and NEON code cannot run on a GPU.
* One change to the sources, applied to the GPU build copy only: QR-UOV
  `qruov.c` has one variable-length array, which PTX cannot hold on the
  stack. It moves to the heap (`patch_gpu` in the recipe). Nothing else
  is changed.

## What the build already shows (checked on the build server)

| Recipe | Result | Registers | Stack per thread |
|---|---|---|---|
| ML-DSA-44, FN-DSA-512, SLH-DSA-128s, Ed25519, ECDSA P-256 | builds | 109–246 | 1–37 KB |
| FAEST 128f, em_128f | builds | 255 | 9–11 KB, plus device heap |
| MQOM gf16_short_ct | builds | 255 | 6 KB, plus device heap |
| SDitH cat1_short | builds | 255 | 3 KB |
| UOV Ip_pkc | builds | 124 | 5 KB |
| QR-UOV 1q127L10-aes opt | builds | 161 | 39 KB |
| SNOVA I_K mem | builds | 168 | 8 KB |
| SNOVA I_K opt | builds | 254 | 341 KB |
| MAYO_1 | builds | 168 | 765 KB |
| SQIsign p324_3 | no build | – | at least 36 variable-length arrays |

The driver reserves the stack for every thread the GPU can hold at once
(70 SMs × 1,536 threads on the RTX 5070 Ti). Beyond about 140 KB per
thread this exceeds 16 GB, so SNOVA opt and MAYO_1 are expected to stop
at `ERROR,stack_limit`. That is a result for the GPU column of the feasibility table,
like the stack limits on the ESP32.

Global variables that every thread writes are listed as `mutable_globals`.
In MAYO and MQOM they are the volatile helpers of secure memory clearing
and value barriers, which hold no data. In SNOVA opt they are tables that
the first call fills. The result check in `gpu_batch_verify` decides in
every case: a batch counts only when all of its results are correct.

## Files

| File | Role |
|---|---|
| `cc_gpu.py` | compiler wrapper: host object as usual, plus NVPTX bitcode |
| `build_gpu.py` | links, optimises and assembles one cubin per recipe |
| `kernel.c` | `pq_verify`: one thread per signature |
| `libc_gpu.c`, `include/` | device C library |
| `gpu_batch_verify.c` | host program (CUDA driver API): loads the cubin, uploads one batch, times the kernel with CUDA events, checks every result |
| `cpu_batch_verify.c` | CPU batch verifier; with `BATCH_DUMP=file` it writes the batch the GPU verifies |
| `../tools/run_gpu.py` | sweep over modes and batch sizes |
| `../tools/gpu_feasibility.py` | GPU column of the feasibility table |

## Run (on the Zen 5 PC)

See the GPU section of the top-level `README.md`.
