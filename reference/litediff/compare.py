"""Line comparison (§1.3 "Matching", §3.4 whitespace, §5.1 --ignore-* options, §8.2 step 5 levels).

All comparisons are on bytes: the file line's content bytes against the UTF-8 bytes of the
patch line content. Whitespace means SP and TAB only (§3.4).
"""
from __future__ import annotations

import re
from typing import Tuple

from .options import MatchOptions

WS = b" \t"
_WS_RUN = re.compile(rb"[ \t]+")


def strip_trailing(data: bytes) -> bytes:
    """§1.3: trailing whitespace is removed from both sides before every comparison."""
    return data.rstrip(WS)


def key(data: bytes, opts: MatchOptions) -> bytes:
    """Comparison key of one line under the active options (§1.3, §5.1)."""
    s = strip_trailing(data)
    if opts.ignore_all_space:                      # §5.1: overrides the others
        return s.replace(b" ", b"").replace(b"\t", b"")
    if opts.ignore_space_change:                   # §5.1: any run of SP/TAB ≡ any other run
        return _WS_RUN.sub(b" ", s)
    return s


def is_blank_bytes(data: bytes) -> bool:
    """§5.1: a file line that is empty or consists only of whitespace."""
    return data.strip(WS) == b""


def split_indent(data: bytes) -> Tuple[bytes, bytes]:
    """§8.2 step 5: indent = maximal leading run of SP/TAB, rest = the remainder."""
    rest = data.lstrip(WS)
    return data[:len(data) - len(rest)], rest


def remove_all_ws(data: bytes) -> bytes:
    return data.replace(b" ", b"").replace(b"\t", b"")


def contains_scope(line: bytes, scope: bytes, opts: MatchOptions) -> bool:
    """§8.2 step 2a: the line contains the scope text as a substring, under the whitespace rules of
    §1.3 and the active --ignore-* options (applied to both sides)."""
    return key(scope, opts) in key(line, opts)


def classify(anchor: bytes, file_line: bytes) -> str:
    """§8.2 step 5 "E410 difference classification" (the first applicable class).

    "tabs versus spaces when L_a and L_f are not both composed of the same single character kind":
    the union of the characters of both indents is taken; one kind (or none) → leading whitespace."""
    a = strip_trailing(anchor)
    f = strip_trailing(file_line)
    la, ra = split_indent(a)
    lf, rf = split_indent(f)
    if ra == rf:
        kinds = set(la) | set(lf)
        return "tabs-vs-spaces" if len(kinds) > 1 else "leading-whitespace"
    if remove_all_ws(a) == remove_all_ws(f):
        return "internal-whitespace"
    return "other"


def levenshtein(a: str, b: str, cap: int = 4000) -> int:
    a, b = a[:cap], b[:cap]
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
