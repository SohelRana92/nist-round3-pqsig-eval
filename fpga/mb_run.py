#!/usr/bin/env python3
"""mb_run.py - build, run and check recipes on the MicroBlaze (Arty S7-25),
without the Vitis GUI.

  source <Vitis 2025.2>/settings64.sh
  python3 fpga/mb_run.py --recipe ed25519-ref            # one recipe
  python3 fpga/mb_run.py                                 # every recipe of the ESP32 list
  python3 fpga/mb_run.py --build-only                    # compile all, run nothing

Needs, once: the platform and Hello World from fpga/vitis_hello.py (the
platform gives the BSP library and xparameters.h, the Hello World gives
the compiler and the base linker script).

For every recipe:
  1. tools/hbuild.py stages the sources (platform "microblaze");
  2. the MicroBlaze GCC from Vitis compiles them with the CPU options of the
     BSP and -O3, and links against the standalone BSP with a linker script
     that puts code, data, heap and stack in the 256 MB DDR3;
  3. xsdb programs the FPGA, loads the ELF and starts it, while this script
     reads the UART (115200 baud) until DONE;
  4. the KAT rows are compared with results/kat_reference/<recipe>.csv (the
     same recipe on x86-64, where it reproduces the team's known-answer
     file); missing references are made with the x86-generic build.
Results: results/raw/microblaze/<recipe>.csv (+ .log, .done), merged rows in
results/kat_microblaze.csv, failures in results/microblaze_failures.txt.
A recipe with a .done file is skipped unless --force.

The run plan is "sizes;kat 3;stack;speed 100 1": 100 timed runs after one
warm-up, 20 when one operation takes over 1 s (--slow-runs) and 5 when it
takes over 30 s (--very-slow-runs, --very-slow-s). The core runs at
81.25 MHz and its timing varies by well under 1% from run to run, so the
ESP32 plan would take days without changing the medians.
"""
import argparse
import csv
import fcntl
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
H = os.path.join(TOP, "harness")
B = os.path.join(TOP, "build")

# CPU options of the MicroBlaze configuration in fpga/system_bd_s25.tcl, as
# the Vitis 2025.2 BSP build prints them.
MB_FLAGS = ["-mcpu=v11.0", "-mlittle-endian", "-mxl-barrel-shift", "-mxl-pattern-compare",
            "-mno-xl-soft-mul", "-mxl-multiply-high", "-mno-xl-soft-div", "-DSDT"]
DEFAULT_PLAN = "sizes;kat 3;stack;speed 100 1"


def die(msg):
    sys.exit("mb_run: " + msg)


def tool(cc, name):
    """mb-gcc -> mb-ar, microblaze-xilinx-elf-gcc -> microblaze-xilinx-elf-ar."""
    d, b = os.path.split(cc)
    return os.path.join(d, b[:-3] + name) if b.endswith("gcc") else name


def find_ws_files(ws):
    plat = os.path.join(ws, "pqsig_plat", "export", "pqsig_plat", "sw", "standalone_microblaze_0")
    if not os.path.isdir(plat):
        die("platform not found at %s; run fpga/vitis_hello.py first" % plat)
    spec = os.path.join(plat, "Xilinx.spec")
    inc = os.path.join(plat, "include")
    lib = os.path.join(plat, "lib")
    xpar = os.path.join(inc, "xparameters.h")
    lscript = os.path.join(ws, "hello_world", "src", "lscript.ld")
    for f in (spec, xpar, lscript):
        if not os.path.exists(f):
            die("missing %s; run fpga/vitis_hello.py first" % f)
    return spec, inc, lib, xpar, lscript


def find_cc(ws):
    """The compiler Vitis used for the Hello World, else one on PATH."""
    for cc_json in glob.glob(os.path.join(ws, "hello_world", "**", "compile_commands.json"), recursive=True):
        try:
            for e in json.load(open(cc_json)):
                cmd = e.get("command") or " ".join(e.get("arguments", []))
                first = cmd.split()[0]
                if "gcc" in os.path.basename(first) and os.path.exists(first):
                    return first
        except (ValueError, IndexError, OSError):
            pass
    for name in ("microblaze-xilinx-elf-gcc", "mb-gcc"):
        p = shutil.which(name)
        if p:
            return p
    root = os.environ.get("XILINX_VITIS", "")
    hits = glob.glob(os.path.join(root, "gnu", "microblaze", "**", "microblaze-xilinx-elf-gcc"), recursive=True)
    if hits:
        return hits[0]
    die("MicroBlaze GCC not found: source Vitis settings64.sh")


def hw_defines(xpar):
    """Timer and GPIO base addresses and the CPU clock from xparameters.h."""
    txt = open(xpar).read()
    macros = dict(re.findall(r"#define\s+(XPAR_\w+)\s+(0x[0-9A-Fa-f]+|\d+)U?L?\b", txt))
    def pick(pattern, exclude=None):
        for k in sorted(macros):
            if re.search(pattern, k) and not (exclude and re.search(exclude, k)):
                return k, macros[k]
        return None, None
    tk, tv = pick(r"(AXI_TIMER|TMRCTR)_0_BASEADDR$")
    gk, gv = pick(r"(AXI_GPIO|XGPIO|GPIO)_0_BASEADDR$")
    ck, cv = pick(r"CPU_CORE_CLOCK_FREQ_HZ$|MICROBLAZE(_0)?_(CORE_CLOCK|CPU_CLK)_FREQ(_HZ)?$|CPU_CLK_FREQ_HZ$")
    if not tv:
        die("no AXI Timer base address in %s" % xpar)
    d = ["-DPQ_TMR_BASE=%s" % tv]
    if gv:
        d.append("-DPQ_GPIO_BASE=%s" % gv)
    if cv and int(cv, 0) > 1000000:
        d.append("-DPQ_CPU_HZ=%su" % int(cv, 0))
    info = "timer %s=%s gpio %s=%s clock %s=%s" % (tk, tv, gk, gv, ck, cv)
    return d, info


def make_lscript(base, out, stack, heap):
    """Hello World linker script with every section moved to the DDR region
    and the stack and heap sizes set."""
    s = open(base).read()
    mem = re.search(r"MEMORY\s*\{(.*?)\}", s, re.S)
    if not mem:
        die("no MEMORY block in %s" % base)
    regions = re.findall(r"^\s*(\w+)\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+)\s*,\s*LENGTH\s*=\s*(0x[0-9A-Fa-f]+)",
                         mem.group(1), re.M)
    ddr = [r for r in regions if int(r[1], 16) == 0x80000000] or \
        sorted(regions, key=lambda r: -int(r[2], 16))[:1]
    if not ddr:
        die("no memory regions in %s" % base)
    ddr = ddr[0][0]
    for name, _, _ in regions:
        if name != ddr:
            s = re.sub(r">\s*%s\b" % re.escape(name), "> " + ddr, s)
    s = re.sub(r"_STACK_SIZE\s*=[^;]*;", "_STACK_SIZE = 0x%x;" % stack, s, count=1)
    s = re.sub(r"_HEAP_SIZE\s*=[^;]*;", "_HEAP_SIZE = 0x%x;" % heap, s, count=1)
    with open(out, "w") as f:
        f.write("/* Made by fpga/mb_run.py from %s: all sections in %s. */\n" % (base, ddr) + s)
    return ddr


def stage(recipe):
    r = subprocess.run([sys.executable, os.path.join(TOP, "tools", "hbuild.py"), "--recipe", recipe,
                        "--platform", "microblaze"], capture_output=True, text=True)
    man = os.path.join(B, "microblaze", recipe, "manifest.json")
    if r.returncode != 0 or not os.path.exists(man):
        return None, (r.stdout + r.stderr)[-2000:]
    return json.load(open(man)), ""


def build(recipe, man, a, tools):
    cc, spec, inc, lib, lscript_base, hwdefs = tools
    out = os.path.join(B, "microblaze", recipe, "mb")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "obj"))
    log = open(os.path.join(out, "build_log.txt"), "w")
    common = [cc] + MB_FLAGS + ["-specs=" + spec, "-I" + inc] + man["cflags"] + \
        ["-ffunction-sections", "-fdata-sections"]
    defs = ["-D" + d for d in man["defines"]]
    incs = ["-I" + d for d in man["include_dirs"]]

    def cc_run(args):
        log.write(" ".join(args) + "\n")
        log.flush()
        return subprocess.run(args, stdout=log, stderr=subprocess.STDOUT).returncode == 0

    objs = []
    for i, s in enumerate(man["sources"] + man["harness_sources"]):
        o = os.path.join(out, "obj", "%03d_%s.o" % (i, os.path.basename(s)[:-2]))
        if not cc_run(common + defs + incs + ["-c", s, "-o", o]):
            return None, "compile failed: %s" % os.path.basename(s)
        objs.append(o)
    # Scheme and harness crypto go into an archive, as in tools/hbuild.py:
    # a file that both the recipe and the bench driver list (hsha256.c for
    # ECDSA) is then linked once instead of twice.
    libscheme = os.path.join(out, "libscheme.a")
    if not cc_run([tool(cc, "ar"), "rcs", libscheme] + objs):
        return None, "archive failed"
    objs = []

    plan = [p.strip().split() for p in a.plan.split(";") if p.strip()]
    main_c = os.path.join(out, "main.c")
    with open(main_c, "w") as f:
        f.write("/* Generated by fpga/mb_run.py. Plan: %s */\n" % a.plan)
        f.write("#include <stdio.h>\nint harness_run(int argc, char **argv);\n")
        for i, p in enumerate(plan):
            f.write("static char *plan_%d[] = { \"bench\", %s };\n" % (i, ", ".join('"%s"' % x for x in p)))
        f.write("int main(void)\n{\n    printf(\"NOTE,mb_start\\r\\n\");\n")
        for i, p in enumerate(plan):
            f.write("    harness_run(%d, plan_%d);\n" % (len(p) + 1, i))
        f.write('    printf("DONE\\r\\n");\n    fflush(stdout);\n    for (;;) { }\n}\n')

    flag_str = " ".join(man["cflags"] + defs).replace(",", ";").replace('"', "")
    ident = ['-DHARNESS_SCHEME="%s"' % man["scheme"], '-DHARNESS_PARAM="%s"' % man["param"],
             '-DHARNESS_VARIANT="%s"' % man["variant"], '-DHARNESS_PLATFORM="microblaze"',
             '-DHARNESS_CFLAGS="%s"' % flag_str, "-DHARNESS_SLOW_RUNS=%d" % a.slow_runs,
             "-DHARNESS_VERY_SLOW_RUNS=%d" % a.very_slow_runs,
             "-DHARNESS_VERY_SLOW_NS=%dULL" % int(a.very_slow_s * 1e9)]
    bdefs = ["-D" + d for d in man.get("bench_defines", [])]
    hsrc = [os.path.join(H, "src", "bench_main.c"), os.path.join(H, "src", "hsha256.c"),
            os.path.join(H, "platform", "plat_microblaze.c"), main_c]
    for s in hsrc:
        o = os.path.join(out, "obj", "h_%s.o" % os.path.basename(s)[:-2])
        if not cc_run(common + defs + bdefs + ident + hwdefs + incs + ["-c", s, "-o", o]):
            return None, "compile failed: %s" % os.path.basename(s)
        objs.append(o)

    ld = os.path.join(out, "lscript.ld")
    make_lscript(lscript_base, ld, a.stack_mb << 20, a.heap_mb << 20)
    elf = os.path.join(out, recipe + ".elf")
    link = [cc] + MB_FLAGS + ["-specs=" + spec, "-Wl,--no-relax", "-Wl,--gc-sections", "-Wl,-T," + ld,
                              "-L" + lib, "-o", elf] + objs + [libscheme] + \
        ["-Wl,--start-group,-lxilstandalone,-lxiltimer,-lgloss,-lxil,-lgcc,-lc,-lm", "-Wl,--end-group",
         "-Wl,-Map," + os.path.join(out, recipe + ".map")]
    if not cc_run(link):
        # Older BSPs have no libxiltimer or libxilstandalone.
        link = [x for x in link if not x.startswith("-Wl,--start-group")] + \
            ["-Wl,--start-group,-lxil,-lgcc,-lc,-lm", "-Wl,--end-group"]
        if not cc_run(link):
            return None, "link failed"
    size = subprocess.run([tool(cc, "size"), elf], capture_output=True, text=True).stdout
    with open(os.path.join(out, "size.txt"), "w") as f:
        f.write(size)
    return elf, ""


def xsdb(tcl, name, timeout):
    path = os.path.join(B, "microblaze", name)
    open(path, "w").write(tcl)
    return subprocess.run(["xsdb", path], capture_output=True, text=True, timeout=timeout)


def xsdb_ok(r):
    return r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower()


def xsdb_program(bit):
    """Configure the FPGA. The first JTAG access can reset the board's USB
    chip, so this runs before the UART is opened."""
    return xsdb("connect\nfpga -f {%s}\nafter 1500\ndisconnect\n" % bit, "program.tcl", 300)


def xsdb_load(elf):
    return xsdb("connect\n"
                "targets -set -nocase -filter {name =~ \"*microblaze*#0\"}\n"
                "rst -processor\n"
                "dow {%s}\n"
                "con\n"
                "after 200\n"
                "disconnect\n" % elf, "load.tcl", 600)


def xsdb_regs():
    tcl = ("connect\n"
           "targets -set -nocase -filter {name =~ \"*microblaze*#0\"}\n"
           "stop\nputs [rrd pc]\nputs [rrd msr]\nputs [rrd ear]\nputs [rrd esr]\n"
           "disconnect\n")
    p = os.path.join(B, "microblaze", "regs.tcl")
    open(p, "w").write(tcl)
    r = subprocess.run(["xsdb", p], capture_output=True, text=True, timeout=120)
    return " ".join((r.stdout + r.stderr).split())


def stable_port(port):
    """/dev/serial/by-id name of the port, which survives re-enumeration."""
    real = os.path.realpath(port)
    for p in glob.glob("/dev/serial/by-id/*"):
        if os.path.realpath(p) == real:
            return p
    return port


def port_users(port):
    """Other processes that hold the port open (a forgotten miniterm)."""
    real = os.path.realpath(port)
    users = []
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.readlink(fd) == real:
                pid = fd.split("/")[2]
                if int(pid) != os.getpid():
                    cmd = open("/proc/%s/cmdline" % pid).read().replace("\0", " ").strip()
                    users.append("%s %s" % (pid, cmd[:80]))
        except OSError:
            pass
    return sorted(set(users))


def open_port(port, baud, wait_s=30):
    import serial
    end = time.time() + wait_s
    while True:
        try:
            return serial.Serial(port, baud, timeout=1)
        except (serial.SerialException, OSError):
            if time.time() > end:
                raise
            time.sleep(1)


def capture(port, baud, out, idle_s, total_s, start):
    """Read the UART until DONE. Returns 'done', 'idle', 'timeout', 'serial'
    (the port was lost) or 'xsdb' (loading failed)."""
    import serial
    s = open_port(port, baud)
    s.reset_input_buffer()
    if not start():
        s.close()
        return "xsdb"
    keep = ("SIZES", "KAT", "SPEED", "STACK", "ENERGY", "NOTE", "ERROR")
    last = time.time()
    end = last + total_s
    state = "timeout"
    with open(out, "w") as f, open(out + ".log", "w") as lg:
        while time.time() < end:
            try:
                raw = s.readline()
            except (serial.SerialException, OSError) as e:
                # A USB glitch: reopen and go on; the board keeps running.
                lg.write("# serial error: %s; reopening\n" % e)
                print("   serial error, reopening the port", flush=True)
                try:
                    s.close()
                    s = open_port(port, baud)
                    continue
                except (serial.SerialException, OSError):
                    state = "serial"
                    break
            if not raw:
                if time.time() - last > idle_s:
                    state = "idle"
                    break
                continue
            last = time.time()
            line = raw.decode("utf-8", "replace").strip()
            lg.write(line + "\n")
            lg.flush()
            if line.startswith(keep):
                f.write(line + "\n")
                f.flush()
                if line.startswith(("KAT,", "SIZES,", "STACK,", "ERROR", "NOTE")):
                    print("   " + line[:150], flush=True)
                elif line.startswith("SPEED,"):
                    # progress: the first run of each operation, then every 10th
                    p = line.split(",")
                    if len(p) > 9 and p[7].isdigit() and int(p[7]) % 10 == 0:
                        print("   SPEED %s run %s: %.3f s" % (p[6], p[7], int(p[9]) / 1e9), flush=True)
            if line == "DONE":
                state = "done"
                break
    try:
        s.close()
    except Exception:
        pass
    return state


def kat_rows(path):
    out = []
    if os.path.exists(path):
        for r in csv.reader(open(path)):
            if r and r[0] == "KAT":
                out.append((r[1], r[2], r[3], r[5:]))
    return out


def reference(recipe, n):
    ref = os.path.join(TOP, "results", "kat_reference", recipe + ".csv")
    if len(kat_rows(ref)) >= n:
        return ref
    r = subprocess.run([sys.executable, os.path.join(TOP, "tools", "hbuild.py"), "--recipe", recipe,
                        "--platform", "x86-generic"], capture_output=True, text=True)
    bench = os.path.join(B, "x86-generic", recipe, "bench")
    if not os.path.exists(bench):
        return None
    k = subprocess.run([bench, "kat", str(n)], capture_output=True, text=True)
    os.makedirs(os.path.dirname(ref), exist_ok=True)
    with open(ref, "w") as f:
        f.write(k.stdout)
    return ref


def kat_check(recipe, out, n):
    got = kat_rows(out)
    ref = reference(recipe, n)
    if not got:
        return "", "", "", "FAIL", "no KAT rows in the MicroBlaze output"
    scheme, param, variant = got[0][:3]
    if not ref:
        return scheme, param, variant, "FAIL", "no x86-64 reference"
    exp = kat_rows(ref)[:len(got)]
    same = len(got) == n and [g[3] for g in got] == [e[3] for e in exp]
    det = "%d vectors %s the x86-64 reference" % (len(got), "match" if same else "differ from")
    return scheme, param, variant, "PASS" if same else "FAIL", det


def merge_kat(row):
    path = os.path.join(TOP, "results", "kat_microblaze.csv")
    hdr = ["recipe", "scheme", "param", "variant", "platform", "method", "status", "detail"]
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rows = {}
        if os.path.exists(path):
            for r in csv.DictReader(open(path)):
                rows[r["recipe"]] = r
        rows[row["recipe"]] = row
        with open(path + ".tmp", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hdr)
            w.writeheader()
            for k in sorted(rows):
                w.writerow(rows[k])
        os.replace(path + ".tmp", path)


def fail_note(msg):
    with open(os.path.join(TOP, "results", "microblaze_failures.txt"), "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M ") + msg + "\n")


def default_recipes():
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(TOP, "results", "kat_reference", "*.csv")))
    first = [n for n in ("ed25519-ref", "ecdsa-p256-ref", "mldsa-44-ref", "fndsa-512-ref") if n in names]
    return first + [n for n in names if n not in first]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", action="append", default=[])
    ap.add_argument("--match", default="")
    ap.add_argument("--ws", default=os.path.join(B, "vitis_ws"))
    ap.add_argument("--bit", default="")
    ap.add_argument("--port", default="/dev/ttyUSB1")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--plan", default=DEFAULT_PLAN)
    ap.add_argument("--slow-runs", type=int, default=20, help="runs when one operation takes over 1 s")
    ap.add_argument("--very-slow-runs", type=int, default=5)
    ap.add_argument("--very-slow-s", type=float, default=30.0,
                    help="runs drop to --very-slow-runs when one operation takes over this many seconds")
    ap.add_argument("--stack-mb", type=int, default=8)
    ap.add_argument("--heap-mb", type=int, default=128)
    ap.add_argument("--idle-min", type=float, default=60, help="no UART line for this long = hang")
    ap.add_argument("--timeout-h", type=float, default=12)
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tag", default="", help="write to results/raw/microblaze_<tag>/ (e.g. energy), so the "
                    "speed results stay untouched")
    a = ap.parse_args()

    # A suspended laptop stops reading the UART and may cut the board's USB
    # power, which ends the run in a false hang. Hold off sleep, idle
    # suspend and the lid switch for as long as this script runs.
    if not a.build_only and os.environ.get("MB_RUN_INHIBITED") != "1" and shutil.which("systemd-inhibit"):
        what = "--what=sleep:idle:handle-lid-switch"
        if subprocess.run(["systemd-inhibit", what, "true"], capture_output=True).returncode == 0:
            os.environ["MB_RUN_INHIBITED"] = "1"
            os.execvp("systemd-inhibit", ["systemd-inhibit", what, "--who=mb_run.py",
                                          "--why=MicroBlaze benchmark on the UART",
                                          sys.executable, "-u"] + sys.argv)
        print("note: could not block suspend; keep the laptop awake and the lid open", flush=True)

    ws = os.path.abspath(a.ws)
    spec, inc, lib, xpar, lscript = find_ws_files(ws)
    cc = find_cc(ws)
    hwdefs, info = hw_defines(xpar)
    bit = a.bit or os.path.join(B, "fpga_s25", "pqsig_mb.runs", "impl_1", "system_wrapper.bit")
    if not os.path.exists(bit):
        hits = glob.glob(os.path.join(ws, "pqsig_plat", "**", "*.bit"), recursive=True)
        bit = hits[0] if hits else ""
    if not a.build_only:
        if not bit:
            die("bitstream not found; pass --bit")
        if not shutil.which("xsdb"):
            die("xsdb not on PATH: source Vitis settings64.sh")
    port = stable_port(a.port)
    print("compiler %s\n%s\nbitstream %s\nuart %s\nsuspend blocked: %s" % (
        cc, info, bit or "-", port, "yes" if os.environ.get("MB_RUN_INHIBITED") == "1" else "no"), flush=True)
    if not a.build_only:
        others = port_users(port)
        if others:
            die("%s is open in another program; close it first:\n  %s" % (port, "\n  ".join(others)))
    tools = (cc, spec, inc, lib, lscript, hwdefs)

    n_kat = 0
    for p in a.plan.split(";"):
        q = p.split()
        if q and q[0] == "kat" and len(q) > 1:
            n_kat = int(q[1])
    raw = os.path.join(TOP, "results", "raw", "microblaze" + ("_" + a.tag if a.tag else ""))
    os.makedirs(raw, exist_ok=True)
    names = a.recipe or [n for n in default_recipes() if a.match in n]
    for n in names:
        out = os.path.join(raw, n + ".csv")
        done = os.path.join(raw, n + ".done")
        if os.path.exists(done) and not a.force and not a.build_only:
            print("skip %s (done)" % n)
            continue
        print("== %s" % n, flush=True)
        man, err = stage(n)
        if not man:
            print("   staging failed")
            fail_note("%s staging failed: %s" % (n, err.strip().splitlines()[-1] if err.strip() else ""))
            continue
        elf, err = build(n, man, a, tools)
        if not elf:
            print("   %s (see build/microblaze/%s/mb/build_log.txt)" % (err, n))
            fail_note("%s %s" % (n, err))
            open(out, "w").write("ERROR,%s,%s,%s,microblaze,build,%s\n" % (man["scheme"], man["param"],
                                                                           man["variant"], err.replace(",", ";")))
            if not a.build_only:
                open(done, "w").close()
            continue
        print("   built %s" % os.path.relpath(elf, TOP), flush=True)
        if a.build_only:
            continue
        t0 = time.time()
        res = {}

        res["x"] = xsdb_program(bit)
        if not xsdb_ok(res["x"]):
            x = res["x"]
            print("   FPGA programming failed:\n" + (x.stdout + x.stderr)[-800:])
            fail_note("%s xsdb program failed" % n)
            continue
        others = port_users(port)
        if others:
            die("%s is open in another program; close it first:\n  %s" % (port, "\n  ".join(others)))

        def start():
            res["x"] = xsdb_load(elf)
            return xsdb_ok(res["x"])
        state = capture(port, a.baud, out, a.idle_min * 60, a.timeout_h * 3600, start)
        if state == "serial":
            print("   the serial port disappeared; recipe not marked done")
            fail_note("%s serial port lost" % n)
            continue
        if state == "xsdb":
            x = res["x"]
            print("   xsdb failed:\n" + (x.stdout + x.stderr)[-800:])
            fail_note("%s xsdb failed" % n)
            continue
        mins = (time.time() - t0) / 60
        if state != "done":
            regs = xsdb_regs()
            with open(out, "a") as f:
                f.write("ERROR,%s,%s,%s,microblaze,%s,after_min,%.0f,%s\n" % (
                    man["scheme"], man["param"], man["variant"], "hang" if state == "idle" else "timeout",
                    mins, regs.replace(",", ";")[:300]))
            fail_note("%s %s after %.0f min; %s" % (n, state, mins, regs[:200]))
            print("   %s after %.0f min; registers: %s" % (state, mins, regs[:200]))
        if n_kat:
            s, p, v, status, det = kat_check(n, out, n_kat)
            merge_kat({"recipe": n, "scheme": s, "param": p, "variant": v, "platform": "microblaze",
                       "method": "compare_x86_reference", "status": status, "detail": det})
            print("   KAT %s: %s; %.1f min" % (status, det, mins), flush=True)
        else:
            print("   %s; %.1f min" % (state, mins), flush=True)
        # A hang or timeout is a result too; --force runs the recipe again.
        open(done, "w").close()


if __name__ == "__main__":
    main()
