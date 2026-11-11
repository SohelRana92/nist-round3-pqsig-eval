# nist-round3-pqsig-eval

Code and data for the paper

> **From Sensor Node to GPU Server: Speed, Energy and Timing Leakage of the Eight NIST Round-3 Post-Quantum Signatures Across the IoT Hierarchy**
> Sohel Rana and M. Rubaiyat Hossain Mondal. Submitted to *IEEE Internet of Things Journal*.

The repository measures the eight NIST Round-3 additional signature candidates (FAEST, MQOM, SDitH, UOV, MAYO, QR-UOV, SNOVA, SQIsign) and six deployed baselines (ML-DSA-44, FN-DSA-512, SLH-DSA-SHA2-128s and -128f, Ed25519, ECDSA P-256) on five platforms:

| Tier | Platform |
|---|---|
| Sensor node | ESP32 (ESP32-D0WD-V3, 240 MHz, 520 KB SRAM, no PSRAM) |
| Edge gateway | Raspberry Pi 5 (Cortex-A76, 2.4 GHz) |
| Server | AMD Ryzen 9 9950X with an NVIDIA RTX 5070 Ti |
| Custom silicon | MicroBlaze soft core on a Digilent Arty S7-25 (81.25 MHz, DDR3L) |

One rule holds everywhere: **a build is never timed on a platform until it passes its known-answer test (KAT) on that platform.** `tools/run_bench.py`, `tools/run_batch.py` and `fpga/mb_run.py` enforce it.

The full raw data (about 490 MB) is archived on Zenodo: DOI *to be added*. This repository holds the code and the summary results the paper's tables and figures are built from.

## Layout

| Path | Contents |
|---|---|
| `harness/` | C benchmark framework: NIST signature API driver, NIST AES-256 CTR-DRBG, platform layers (Linux, ESP32, MicroBlaze), cycle and stack measurement, energy markers, baseline wrappers |
| `registry/recipes.json` | 464 build recipes: every parameter set of every candidate, in reference, portable and submitters' optimised builds |
| `tools/` | build, KAT, speed, batch, GPU, RAPL, PMIC and timing-test runners; feasibility classifiers; package checks |
| `kat/` | KAT checking helpers |
| `ct/` | fixed-versus-random timing test (dudect method) and Valgrind memcheck secret-dependence test |
| `gpu/` | OpenMP CPU batch verifier and the CUDA (NVPTX) batch verifier; see `gpu/README.md` |
| `esp32/` | ESP-IDF project generator |
| `fpga/` | Vivado block design and build script, Vitis app generator, MicroBlaze runner |
| `energy/` | RAPL, Raspberry Pi 5 PMIC and Vivado-estimate energy analysis |
| `paper/scripts/`, `paper/data/` | scripts that regenerate every table and figure of the paper from `results/` |
| `results/` | summary results (see `results/README.md`) |

## Requirements

* Linux with GCC 14 (the x86 PCs and the Pi 5 used GCC 14.2.0), Python 3.10 or later, `git`, `make`, `cmake`, `meson`, `ninja`, OpenSSL headers.
* Python packages for the analysis: `matplotlib` (figures only).
* ESP32: ESP-IDF v5.4.4.
* MicroBlaze: Vivado and Vitis 2025.2, Digilent Arty S7-25.
* GPU: clang/LLVM 18 with the NVPTX target, CUDA toolkit (`ptxas`, driver API), an NVIDIA GPU.

## 1. Get the candidate sources

The candidates' code is not copied into this repository. `tools/fetch_sources.sh` clones each team's repository at the commit we validated and prepares the NIST-layout folders:

```sh
sh tools/fetch_sources.sh                       # into ~/pqsig-src
PQSIG_SOURCES=/data/pqsig-src sh tools/fetch_sources.sh
```

`results/package_hashes.csv` lists the official NIST Round-3 packages (SHA-256, download date). `tools/check_official_pkgs.py` and `tools/compare_pkg_rsp.py` confirm that those packages give the same KAT output as the builds measured here:

```sh
python3 tools/check_official_pkgs.py ~/pqc-pkgs
python3 tools/compare_pkg_rsp.py ~/pqc-pkgs ~/pqsig-src
```

## 2. Quick check on any Linux PC

```sh
python3 tools/hbuild.py --recipe mayo-MAYO_1-ref --platform x86-generic
build/x86-generic/mayo-MAYO_1-ref/bench sizes
python3 tools/kat_all.py --platform x86-generic --match mayo-MAYO_1-ref --vectors 3
```

## 3. Reproduce the measurements

Fix the CPU state before timing: set the governor to `performance`, turn CPU boost off on x86, and keep the machine otherwise idle. `tools/sysinfo.sh` records the state before and after a session.

**KAT on every platform first**

```sh
python3 tools/kat_all.py --platform x86 --category 1
python3 tools/kat_all.py --platform pi5 --category 1
```

**Speed and stack (Ryzen 9 9950X, Raspberry Pi 5)**

```sh
python3 tools/run_bench.py --platform x86 --category 1
python3 tools/run_bench.py --platform pi5 --category 1
python3 tools/summarize.py
```

**ESP32**

```sh
esp32/make_project.py --recipe uov-Ip-ref-portable --out ~/esp/uov --plan "sizes;kat 3;stack;speed 1000 10"
cd ~/esp/uov && idf.py set-target esp32 && idf.py build flash
tools/esp32_capture.py --port /dev/ttyUSB0 --out results/raw/esp32/uov-Ip-ref-portable.csv
python3 tools/esp32_feasibility.py
```

**MicroBlaze (Arty S7-25)**

```sh
vivado -mode batch -nojournal -source fpga/build_mb.tcl -tclargs build/fpga_s25
source <Vitis 2025.2>/settings64.sh
python3 fpga/vitis_hello.py            # once: platform and base linker script
python3 fpga/mb_run.py                 # build, run and KAT-check every recipe
```

**Timing-leakage tests (x86 and Pi 5)**

```sh
python3 tools/run_ct_all.py --platform x86 --control
python3 tools/run_ct_all.py --platform x86 --followup
sh ct/run_ct.sh uov-Ip-ref-portable x86  # one recipe: both tests, incl. Valgrind memcheck
```

**Batch verification on the CPU and the GPU**

```sh
python3 tools/run_batch.py --platform x86 --omp-active
sudo nvidia-smi --lock-gpu-clocks=2295,2295     # lock the GPU clock first
python3 tools/run_gpu.py --cpu-platform x86 --batch-budget-s 2400
python3 tools/gpu_feasibility.py
```

**Energy**

```sh
sudo chmod o+r /sys/class/powercap/intel-rapl:0/energy_uj     # once per boot
python3 tools/run_rapl.py && python3 energy/rapl_session.py results/raw/x86/rapl_*.csv
python3 tools/pi_pmic_energy.py && python3 energy/board_session.py --label pi5 results/raw/energy/pi5_pmic
python3 energy/vivado_estimate.py      # MicroBlaze estimate from results/fpga/power.rpt
```

Every runner skips what is already finished, so a run can be restarted after an interruption.

## 4. Regenerate the tables and figures

```sh
python3 paper/scripts/make_tables.py   # paper/tables/*.tex
python3 paper/scripts/table_ix.py      # message-size table
python3 paper/scripts/figs.py          # paper/figures/fig3_cycles.pdf, fig4_energy.pdf, fig5_batch.pdf
python3 paper/scripts/fig_hierarchy.py # paper/figures/fig0_hierarchy.pdf
```

With the files in `results/` these scripts reproduce the paper's tables exactly.

## Licence

The code in this repository is released under the MIT licence (`LICENSE`). The data in `results/` and in the Zenodo archive are released under CC BY 4.0. Third-party files keep their own licences: see `harness/common/SOURCE.txt` and `harness/baselines/SOURCES.md`. The candidate implementations are fetched from their teams' repositories and are not redistributed here.

## Citation

See `CITATION.cff`. Please cite the paper once it is published.
