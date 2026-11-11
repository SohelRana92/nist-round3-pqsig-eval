#!/usr/bin/env python3
"""cc_gpu.py - compiler wrapper that also emits GPU (NVPTX) bitcode.

hbuild.py --platform gpu uses this file as its C compiler, including inside
the teams' own make and CMake builds. For every call it

  1. runs the host compiler with the unchanged arguments, so the normal
     x86-64 build, its tests and its archive come out exactly as usual;
  2. when the call compiles one C file to an object (-c file.c -o file.o),
     compiles the same file once more with
        clang --target=nvptx64-nvidia-cuda -emit-llvm
     using the same -D, -U, -I, -include and -std options, and writes the
     result next to the object as file.o.nvbc.

Step 2 never fails the build: a file that does not compile for the GPU
(a test program, a file that uses the operating system) leaves a
file.o.nvbc.log instead, and gpu/build_gpu.py decides later whether the
verification code needs it.

Environment
  PQSIG_GPU_HOSTCC   host compiler (default gcc)
  PQSIG_GPU_CLANG    clang with the NVPTX back end (default clang)
  PQSIG_GPU_ARCH     PTX target for clang (default sm_89; ptxas turns the
                     PTX into sm_120 machine code for the RTX 5070 Ti)
  PQSIG_GPU_LIST     file to which one line per object is appended:
                     object path, bitcode path, status, source path
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Options with a separate argument that must be kept or dropped together.
KEEP_WITH_ARG = {"-I", "-D", "-U", "-include", "-isystem", "-iquote", "-idirafter", "-imacros"}
DROP_WITH_ARG = {"-o", "-MF", "-MT", "-MQ", "-x", "-arch", "-Xlinker", "-L", "-l"}


def gpu_args(args):
    keep = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in KEEP_WITH_ARG and i + 1 < len(args):
            keep += [a, args[i + 1]]
            i += 2
            continue
        if a in DROP_WITH_ARG:
            i += 2
            continue
        if a.startswith(("-D", "-U", "-I", "-std=", "-iquote", "-isystem")):
            keep.append(a)
        elif a.startswith("-include"):
            keep.append(a)
        # Everything else is a host option (-O, -m, -f, -g, -W, -M...) or
        # the source and object names, which the caller sets anew.
        i += 1
    return keep


def main():
    args = sys.argv[1:]
    host = os.environ.get("PQSIG_GPU_HOSTCC", "gcc")
    r = subprocess.run([host] + args)
    if r.returncode != 0:
        sys.exit(r.returncode)
    if "-c" not in args or "-o" not in args:
        return
    srcs = [a for a in args if a.endswith(".c") and not a.startswith("-")]
    if len(srcs) != 1:
        return
    src = srcs[0]
    obj = args[args.index("-o") + 1]
    bc = obj + ".nvbc"
    clang = os.environ.get("PQSIG_GPU_CLANG", "clang")
    arch = os.environ.get("PQSIG_GPU_ARCH", "sm_89")
    cmd = ([clang, "--target=nvptx64-nvidia-cuda", "-march=" + arch, "-O3", "-emit-llvm", "-c",
            "-nostdlibinc", "-isystem", os.path.join(HERE, "include"), "-DPQSIG_GPU=1",
            "-Wno-everything"]
           + gpu_args(args) + [src, "-o", bc])
    g = subprocess.run(cmd, capture_output=True, text=True)
    status = "ok" if g.returncode == 0 else "fail"
    if g.returncode != 0:
        with open(bc + ".log", "w") as f:
            f.write(" ".join(cmd) + "\n" + g.stdout + g.stderr)
        if os.path.exists(bc):
            os.remove(bc)
    lst = os.environ.get("PQSIG_GPU_LIST")
    if lst:
        with open(lst, "a") as f:
            f.write("%s\t%s\t%s\t%s\n" % (os.path.abspath(obj), os.path.abspath(bc), status,
                                          os.path.abspath(src)))


if __name__ == "__main__":
    main()
