"""Path extraction and processing (§6.3.1 order, §6.3.3–§6.3.6, §5.3 --strip).

Processing order for every path (§6.3.1): (1) unquoting and escape decoding (§6.3.4);
(2) prefix removal (§6.3.5) or component stripping (§5.3) — for `diff --git` and `---`/`+++`
paths only; (3) normalization (§6.3.6); (4) security checks (§6.3.3).

Paths are kept in a canonical form: components joined with "/", Unicode NFC. The conversion
to the OS form ("\\" on Windows) happens only when the file system is touched (workspace.py).
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

DEV_NULL = "/dev/null"

# §6.3.5 letter-prefix rule: exactly these six letters.
LETTER_PREFIXES = ("a/", "b/", "c/", "i/", "o/", "w/")

_SIMPLE_ESCAPES = {
    '"': 0x22, "\\": 0x5C, "n": 0x0A, "r": 0x0D, "t": 0x09,
    # git also writes \a \b \f \v (C escapes); accepted as C-style escapes
    "a": 0x07, "b": 0x08, "f": 0x0C, "v": 0x0B,
}
# §6.3.5 (§12 item 29): "a single letter followed by `:` and `\` or `/` is a Windows drive and the
# path is absolute" on every platform. Checked after normalization, where `\` has become `/`.
_DRIVE_RE = re.compile(r"^[A-Za-z]:/")
# §6.3.5 (§12 item 29): on Windows any path containing `:` is E100 (`c:x.txt` is drive-relative and
# leaves the workspace; `notes:2026.txt` would be an NTFS alternate data stream of `notes`).
_COLON_IS_SPECIAL = os.name == "nt"


class PathError(Exception):
    """A path processing failure with its diagnostic code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------------
# §6.3.4 quoting and escapes
# ---------------------------------------------------------------------------------------------

def parse_quoted(text: str, start: int = 0) -> Tuple[str, int]:
    """Decode a C-quoted string beginning at text[start] == '"'.

    Returns (decoded path, index after the closing quote). Escapes yield bytes, the byte string
    is decoded as UTF-8 (§6.3.4). Raises PathError(E203)."""
    assert text[start] == '"'
    out = bytearray()
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            try:
                return out.decode("utf-8"), i + 1
            except UnicodeDecodeError:
                raise PathError("E203", "quoted path is not valid UTF-8 after escape decoding")
        if ch == "\\":
            if i + 1 >= len(text):
                break
            nxt = text[i + 1]
            if nxt in _SIMPLE_ESCAPES:
                out.append(_SIMPLE_ESCAPES[nxt])
                i += 2
                continue
            if nxt == "x":
                hexdigits = text[i + 2:i + 4]
                if len(hexdigits) == 2 and all(c in "0123456789abcdefABCDEF" for c in hexdigits):
                    out.append(int(hexdigits, 16))
                    i += 4
                    continue
                raise PathError("E203", "invalid \\x escape in quoted path")
            if nxt in "01234567":
                digits = text[i + 1:i + 4]
                if len(digits) == 3 and all(c in "01234567" for c in digits):
                    value = int(digits, 8)
                    if value > 0o377:   # \400-\777 are invalid (§6.3.4)
                        raise PathError("E203", "octal escape \\%s out of range \\000-\\377" % digits)
                    out.append(value)
                    i += 4
                    continue
                raise PathError("E203", "octal escape must have three digits")
            raise PathError("E203", "invalid escape sequence \\%s in quoted path" % nxt)
        out.extend(ch.encode("utf-8"))
        i += 1
    raise PathError("E203", "quoted path has no closing quote")


def split_header_path(text: str) -> str:
    """§6.3.4: the path part of a `---`/`+++` line (text after the lexeme's space or tab).

    Quoted: up to the matching quote; unquoted: up to the first tab (a tab and anything after it
    is the timestamp), trailing spaces removed (§12 item 28). Returns the *raw* path (still
    quoted if it was quoted)."""
    if text.startswith('"'):
        _, end = parse_quoted(text, 0)
        return text[:end]
    tab = text.find("\t")
    return strip_unquoted(text if tab < 0 else text[:tab])


def strip_unquoted(raw: str) -> str:
    """§6.3.4 (§12 item 28): trailing spaces and tabs are removed from an unquoted path.

    The text states this for `---`/`+++` paths. It is applied to the unquoted `diff --git` remainder
    and to unquoted `rename`/`copy` paths as well (spec finding, README): otherwise `+++ x ` and
    `diff --git a/x  b/x ` or `rename to x ` would disagree (E202/E209) about the same file."""
    if raw.startswith('"'):
        return raw
    return raw.rstrip(" \t")


def unquote(raw: str) -> str:
    """Step (1) of the processing order."""
    if raw.startswith('"'):
        value, end = parse_quoted(raw, 0)
        if raw[end:].strip(" \t"):
            raise PathError("E203", "unexpected text after the closing quote")
        return value
    return raw


# ---------------------------------------------------------------------------------------------
# §6.3.5 prefixes, §5.3 --strip
# ---------------------------------------------------------------------------------------------

def letter_prefix(path: str) -> Optional[str]:
    for p in LETTER_PREFIXES:
        if path.startswith(p):
            return p
    return None


def remove_prefix(path: str, strip: Optional[int]) -> str:
    """Step (2): prefix removal for `diff --git` and `---`/`+++` paths.

    With `--strip N` the letter-prefix rule is replaced by component stripping (§5.3). The v1.0
    `<prefix>:` form no longer exists (§12 item 29): a colon is an ordinary character."""
    if path == DEV_NULL:
        return path
    if strip is not None:
        parts = re.split(r"[/\\]", path)
        if len(parts) <= strip:   # §5.3 (§12 item 8): N or fewer components → E104
            raise PathError("E104", "path %r has %d component(s); --strip %d would leave nothing"
                            % (path, len(parts), strip))
        return "/".join(parts[strip:])
    lp = letter_prefix(path)
    if lp:
        path = path[len(lp):]
    return path


# ---------------------------------------------------------------------------------------------
# §6.3.6 normalization, §6.3.3 security
# ---------------------------------------------------------------------------------------------

def normalize(path: str) -> str:
    """Step (3): slashes unified ("\\" is a separator too), Unicode NFC."""
    if path == DEV_NULL:
        return path
    return unicodedata.normalize("NFC", path.replace("\\", "/"))


def security_check(path: str) -> None:
    """Step (4), §6.3.3: E100 absolute, E101 traversal, E102 glob. (E103 needs the file system.)"""
    if path == DEV_NULL:
        return
    if path == "":
        raise PathError("E101", "empty path")
    if path.startswith("/") or _DRIVE_RE.match(path):
        raise PathError("E100", "absolute path %r is prohibited" % path)
    if _COLON_IS_SPECIAL and ":" in path:
        # §6.3.5 (§12 item 29): `c:x.txt` names a file relative to the current directory of drive C:,
        # outside the workspace; `notes:2026.txt` names an NTFS alternate data stream of `notes`
        raise PathError("E100", "path %r contains ':' , which has a file-system meaning on Windows "
                                "(drive-relative path or NTFS alternate data stream)" % path)
    for comp in path.split("/"):
        if comp in (".", ".."):
            raise PathError("E101", "path %r contains a %r component" % (path, comp))
    if "*" in path or "?" in path:
        raise PathError("E102", "path %r contains a glob character" % path)


def process_path(raw: str, kind: str, strip: Optional[int]) -> str:
    """Full processing order of §6.3.1 for one raw path.

    kind: "diff-git" / "header" (prefix removal applies) or "operation" (rename/copy paths:
    unquoted and normalized, never prefix-stripped, §6.3.2)."""
    value = unquote(strip_unquoted(raw))
    if value == DEV_NULL:
        return DEV_NULL
    if kind in ("diff-git", "header"):
        value = remove_prefix(value, strip)
    value = normalize(value)
    security_check(value)
    return value


def process_path_no_security(raw: str, kind: str, strip: Optional[int]) -> Optional[str]:
    """Steps (1)–(3) only; None on any failure. Used by the §4.1 rename-absorption comparison."""
    try:
        value = unquote(strip_unquoted(raw))
        if value == DEV_NULL:
            return DEV_NULL
        if kind in ("diff-git", "header"):
            value = remove_prefix(value, strip)
        return normalize(value)
    except PathError:
        return None


# ---------------------------------------------------------------------------------------------
# §6.3.4 splitting `diff --git <src> <dst>`
# ---------------------------------------------------------------------------------------------

@dataclass
class DiffGitPaths:
    src_raw: str
    dst_raw: str


def _strip_for_compare(path: str, strip: Optional[int]) -> Optional[str]:
    try:
        return normalize(remove_prefix(path, strip))
    except PathError:
        return None


def split_diff_git(rest: str, strip: Optional[int]) -> DiffGitPaths:
    """Split the remainder after `diff --git ` into the two raw paths (§6.3.4). Raises E204/E203."""
    rest = rest.rstrip(" \t")       # trailing whitespace is not part of the destination (see strip_unquoted)
    # quoted source
    if rest.startswith('"'):
        _, end = parse_quoted(rest, 0)
        if end >= len(rest) or rest[end] != " ":
            raise PathError("E204", "cannot split diff --git paths; quote them")
        return DiffGitPaths(rest[:end], rest[end + 1:])
    # unquoted source, quoted destination
    if rest.endswith('"'):
        positions = []
        for i, ch in enumerate(rest):
            if ch == " " and i + 1 < len(rest) and rest[i + 1] == '"' and i > 0:
                try:
                    _, end = parse_quoted(rest, i + 1)
                except PathError:
                    continue
                if end == len(rest):
                    positions.append(i)
        if len(positions) == 1:
            i = positions[0]
            return DiffGitPaths(rest[:i], rest[i + 1:])
    # both unquoted: the single space where the halves are identical after prefix removal ...
    spaces = [i for i, ch in enumerate(rest) if ch == " " and 0 < i < len(rest) - 1]
    identical = []
    for i in spaces:
        a, b = rest[:i], rest[i + 1:]
        sa, sb = _strip_for_compare(a, strip), _strip_for_compare(b, strip)
        if sa is not None and sa == sb:
            identical.append(i)
    if len(identical) == 1:
        i = identical[0]
        return DiffGitPaths(rest[:i], rest[i + 1:])
    if len(identical) > 1:
        raise PathError("E204", "cannot split diff --git paths (%d positions qualify); quote them"
                        % len(identical))
    # ... or, failing that, the single space where both halves are non-empty and the second starts
    # with a letter-prefix when the first does. (With --strip N, where the letter-prefix rule does
    # not apply, both halves must have more than N components.)
    qualifying = []
    for i in spaces:
        a, b = rest[:i], rest[i + 1:]
        if not a or not b:
            continue
        if strip is None:
            if letter_prefix(a) and not letter_prefix(b):
                continue
        else:
            if len(re.split(r"[/\\]", a)) <= strip or len(re.split(r"[/\\]", b)) <= strip:
                continue
        qualifying.append(i)
    if len(qualifying) == 1:
        i = qualifying[0]
        return DiffGitPaths(rest[:i], rest[i + 1:])
    raise PathError("E204", "cannot split diff --git paths (%s); quote them"
                    % ("no position qualifies" if not qualifying else "%d positions qualify" % len(qualifying)))


def components(path: str) -> List[str]:
    return [c for c in path.split("/") if c]
