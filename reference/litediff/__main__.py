"""Command line: `python -m litediff [--check] [--strict] [--eol lf|crlf] <patch-path> <workdir>`.

Applies the patch to the workdir and prints the Appendix B result JSON to stdout.
Exit status: 0 for `applied`/`checked`, 1 for `failed`, 2 for usage errors.
"""
from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

from .engine import apply_document
from .parser import HostOptions
from .result import build_result

USAGE = "usage: python -m litediff [--check] [--strict] [--eol lf|crlf] <patch-path> <workdir>"


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    host = HostOptions()
    positional: List[str] = []
    k = 0
    while k < len(args):
        a = args[k]
        if a == "--check" and not positional:
            host.check = True
        elif a == "--strict" and not positional:
            host.strict = True
        elif a == "--eol" and not positional and k + 1 < len(args) and args[k + 1] in ("lf", "crlf"):
            host.eol = args[k + 1]
            k += 1
        elif a in ("-h", "--help"):
            print(USAGE)
            return 0
        elif a.startswith("--") and not positional:
            print("litediff: unknown switch %s\n%s" % (a, USAGE), file=sys.stderr)
            return 2
        else:
            positional.append(a)
        k += 1
    if len(positional) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    patch_path, workdir = positional
    if not os.path.isdir(workdir):
        print("litediff: workdir %r is not a directory" % workdir, file=sys.stderr)
        return 2
    try:
        with open(patch_path, "rb") as f:
            patch = f.read()
    except OSError as e:
        print("litediff: cannot read patch: %s" % e, file=sys.stderr)
        return 2
    engine = apply_document(patch, workdir, host)
    result = build_result(engine)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    sys.stdout.flush()
    return 0 if result["status"] in ("applied", "checked") else 1


if __name__ == "__main__":
    sys.exit(main())
