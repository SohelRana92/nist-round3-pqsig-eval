#!/usr/bin/env python3
"""memcheck_sites.py - list the distinct code sites in a memcheck.log.

  ct/memcheck_sites.py build/x86/mayo-MAYO_1-ref/memcheck.log

For each report it prints the kind (branch or address), the innermost
frame (function and file:line when the build carries -g) and the frame
that called it. These rows feed the memcheck column of the timing-leakage table. Each site
must then be read in the source and classed by hand as
  public-by-design  (rejection or retry outcome that the signature reveals anyway)
  secret-dependent  (branch or table index on secret data)
The class is a judgement and the paper says who made it.
"""
import re
import sys

KIND = {
    "Conditional jump or move depends on uninitialised value(s)": "branch",
    "Use of uninitialised value of size": "address",
    "Syscall param": "syscall",
}


def main(path):
    lines = open(path, errors="replace").read().splitlines()
    sites = []
    i = 0
    while i < len(lines):
        body = re.sub(r"^==\d+==\s?", "", lines[i])
        kind = next((v for k, v in KIND.items() if body.startswith(k)), None)
        if kind:
            frames = []
            j = i + 1
            while j < len(lines):
                b = re.sub(r"^==\d+==\s+", "", lines[j])
                m = re.match(r"(at|by) 0x[0-9A-F]+: (.*)", b)
                if not m:
                    break
                frames.append(m.group(2))
                j += 1
            sites.append((kind, frames[0] if frames else "?", frames[1] if len(frames) > 1 else ""))
            i = j
        else:
            i += 1
    seen = set()
    print("kind,site,caller")
    for s in sites:
        if s not in seen:
            seen.add(s)
            print("%s,%s,%s" % (s[0], s[1].replace(",", ";"), s[2].replace(",", ";")))


if __name__ == "__main__":
    main(sys.argv[1])
