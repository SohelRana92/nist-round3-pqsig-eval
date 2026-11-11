# Results

Summary files that the paper's tables and figures are built from. All files are CSV with a header row. The full raw data (per-run cycle counts, energy logs, timing-test logs, memcheck output, FPGA reports) is in the Zenodo archive.

Common columns: `scheme`, `param` (parameter set), `variant` (`ref`, `ref-portable`, `opt-*`), `platform` (`esp32`, `pi5`, `x86`, `microblaze`, `gpu`).

| File | Contents |
|---|---|
| `kat_<platform>.csv` | known-answer test result per build: `method`, `status` (PASS, FAIL, EXTERNAL), `detail` |
| `feasibility.csv` | one row per scheme and platform: `status` (runs, no run, no build, key generation only, or the share of parameter sets that build, such as "16 of 20 builds") and the limiting resource |
| `feasibility_sets_esp32.csv`, `feasibility_sets_gpu.csv` | the same per parameter set, with the reason |
| `summary_speed.csv` | per operation: run count, median, quartiles, IQR, p99, min and max in cycles, median in ns, `all_ok` |
| `summary_stack.csv` | peak stack per operation, in bytes above an empty run |
| `summary_sizes.csv` | public key, secret key and signature bytes |
| `summary_code.csv`, `code_microblaze.csv` | code size (`.text`, `.data`, `.bss`) |
| `energy_summary*.csv` | energy per operation in µJ, mean and 95% confidence interval; `_x86_session` and `_pi5_session` use one idle level per session |
| `energy_board_pi5_pmic.csv` | Raspberry Pi 5 PMIC energy per operation |
| `energy_microblaze_vivado.csv` | MicroBlaze estimate: Vivado on-chip power times median time |
| `ct_<platform>.csv` | timing-leakage tests: `test` (fixed-versus-random, control, confirmation, memcheck), number of measurements `n`, `max_abs_t`, `result` |
| `ct_sites_<platform>.csv` | memcheck report sites, classified by hand |
| `ct_x86_v1_singlebuffer.csv`, `ct_x86_v2_separatebuffers.csv` | the x86 timing test before and after the fixed and random inputs were moved to separate buffers |
| `raw/x86/batch_*.csv`, `raw/gpu/batch_*.csv` | batch verification: `device`, `mode`, `threads`, `batch`, `rep`, `ns`, `verifies_per_s`, `all_ok`; GPU files add `GPU_XFER` rows with the host-device copy times |
| `gpu_info.csv`, `gpu_build_summary.json` | GPU model, clocks and per-recipe build data (registers, stack) |
| `package_hashes.csv` | official NIST Round-3 package files with SHA-256 and download date |
| `package_kat_match.csv`, `package_rsp_compare.csv` | checks that the official packages give the same KAT output as the measured builds |

Rows with `all_ok=0` (a verification failed) are kept for completeness and are never reported in the paper.
