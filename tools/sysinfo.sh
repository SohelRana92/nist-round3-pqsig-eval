#!/bin/sh
# sysinfo.sh - record the machine state that the paper's setup table needs.
#   tools/sysinfo.sh > results/sysinfo_$(hostname).txt
# Run it right before and right after each measurement session.
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "host: $(hostname)"
echo "kernel: $(uname -srmv)"
[ -r /etc/os-release ] && . /etc/os-release && echo "os: $PRETTY_NAME"
echo "gcc: $(gcc --version | head -1)"
command -v clang >/dev/null && echo "clang: $(clang --version | head -1)"
command -v nvcc >/dev/null && echo "nvcc: $(nvcc --version | tail -1)"
echo "cpu: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
[ -z "$(grep -m1 'model name' /proc/cpuinfo)" ] && echo "cpu: $(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
echo "cores_online: $(nproc)"
for f in /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor \
         /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq \
         /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq \
         /sys/devices/system/cpu/cpufreq/boost \
         /sys/devices/system/cpu/smt/control \
         /proc/sys/kernel/perf_event_paranoid; do
    [ -r "$f" ] && echo "$f: $(cat $f)"
done
command -v vcgencmd >/dev/null && { echo "pi_temp: $(vcgencmd measure_temp)"; echo "pi_clock_arm: $(vcgencmd measure_clock arm)"; echo "pi_throttled: $(vcgencmd get_throttled)"; }
command -v sensors >/dev/null && sensors 2>/dev/null | grep -E "Tctl|Tccd" | sed 's/^/x86_temp: /'
command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,driver_version,memory.total,clocks.max.sm,power.limit,temperature.gpu --format=csv,noheader | sed 's/^/gpu: /'
echo "flags: $(grep -m1 -o -w -E 'avx2|avx512f|avx512vl|gfni|vaes|vpclmulqdq|aes|sha_ni|adx|bmi2' /proc/cpuinfo | sort -u | tr '\n' ' ')"
grep -m1 Features /proc/cpuinfo | sed 's/^/arm_features: /'
