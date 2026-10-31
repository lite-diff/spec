"""Line lexemes of §3.1 and the hunk header lexeme of §7.1.

Every function here looks at one patch line (a `str` without its line terminator) and
answers a structural question. None of them has state; the state machine of §4.1 lives in
`parser.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# §3.1 metadata keyword lines. The operation-opening keywords are a subset.
METADATA_KEYWORDS = (
    "rename from ", "rename to ", "copy from ", "copy to ",
    "new file mode ", "deleted file mode ", "old mode ", "new mode ",
    "similarity index ", "dissimilarity index ", "index ",
    "Binary files ", "GIT binary patch", "option ",
)
OPERATION_OPENING_KEYWORDS = (
    "rename from ", "copy from ", "new file mode ", "deleted file mode ",
    "similarity index ", "dissimilarity index ",
)

# §5 option grammar: `--<name>` or `--<name> <value>`, name = [a-z][a-z-]*.
_OPTION_RE = re.compile(r"^--([a-z][a-z-]*)(?: (.*))?$")
# §3.1 fence: three or more backticks, optionally followed by a language name.
_FENCE_RE = re.compile(r"^`{3,}[A-Za-z0-9_+.#-]*[ \t]*$")
# §7.1 / §7.2: `...` marker, trailing spaces or tabs allowed, nothing else.
_MARKER_RE = re.compile(r"^\.\.\.[ \t]*$")
# §7.1 form 3: unified header, optionally followed by a space and section text.
_UNIFIED_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: (.*))?$")


def is_blank(line: str) -> bool:
    """§3.1 "Blank line": a line without any characters."""
    return line == ""


def is_comment(line: str) -> bool:
    """§3.1 "Comment": first character `#` (meaningful only in PREAMBLE and HEADER)."""
    return line.startswith("#")


def is_fence(line: str) -> bool:
    """§3.1 fence lexeme."""
    return bool(_FENCE_RE.match(line))


def is_diff_command(line: str) -> bool:
    """§3.1 diff command line: `diff ` followed by anything."""
    return line.startswith("diff ")


def is_diff_git(line: str) -> bool:
    return line.startswith("diff --git ")


def is_minus_path_header(line: str) -> bool:
    """§3.1 path header `---` + space or tab."""
    return line.startswith("--- ") or line.startswith("---\t")


def is_plus_path_header(line: str) -> bool:
    """§3.1 path header `+++` + space or tab."""
    return line.startswith("+++ ") or line.startswith("+++\t")


def is_path_header(line: str) -> bool:
    return is_minus_path_header(line) or is_plus_path_header(line)


def metadata_keyword(line: str) -> Optional[str]:
    """Return the §3.1 metadata keyword the line starts with, or None."""
    for kw in METADATA_KEYWORDS:
        if line.startswith(kw):
            return kw
    return None


def is_metadata(line: str) -> bool:
    return metadata_keyword(line) is not None


def is_operation_opening(line: str) -> bool:
    return any(line.startswith(kw) for kw in OPERATION_OPENING_KEYWORDS)


def option_match(line: str):
    """§5 option grammar. Returns (name, value-or-None) or None. A path header is never an option."""
    if is_path_header(line):
        return None
    m = _OPTION_RE.match(line)
    if not m:
        return None
    return m.group(1), m.group(2)


def is_sentinel(line: str) -> bool:
    """§3.1 sentinel lexeme: backslash followed by a space."""
    return line.startswith("\\ ")


def is_marker(line: str) -> bool:
    """§7.1 / §7.2 boundary marker `...` (trailing whitespace allowed)."""
    return bool(_MARKER_RE.match(line))


def is_hunk_header_candidate(line: str) -> bool:
    """§4.1: in every state a first-position line starting with `@@` is a hunk header candidate."""
    return line.startswith("@@")


@dataclass
class HunkHeader:
    """A parsed hunk header (§7.1). kind: plain / bof / eof / unified / scope."""

    kind: str
    old_start: Optional[int] = None
    old_count: Optional[int] = None   # None = omitted (means 1, §8.2 step 6)
    new_start: Optional[int] = None
    new_count: Optional[int] = None
    scope: Optional[str] = None


def parse_hunk_header(line: str) -> Optional[HunkHeader]:
    """§7.1 "Hunk header lexeme (normative)": the forms are tested in order; None means E403."""
    if not line.startswith("@@"):
        return None
    s = line.rstrip(" \t")  # trailing spaces and tabs are permitted and ignored in all forms
    # form 1
    if s == "@@":
        return HunkHeader("plain")
    # form 2 (uppercase only, exactly one space)
    if s == "@@ BOF":
        return HunkHeader("bof")
    if s == "@@ EOF":
        return HunkHeader("eof")
    # form 3
    m = _UNIFIED_RE.match(s)
    if m:
        return HunkHeader(
            "unified",
            old_start=int(m.group(1)),
            old_count=int(m.group(2)) if m.group(2) is not None else None,
            new_start=int(m.group(3)),
            new_count=int(m.group(4)) if m.group(4) is not None else None,
        )
    # form 4: `@@`, exactly one space, scope text whose first character is not
    # `-`, `+`, `@`, space or tab (§12 item 17).
    if len(s) >= 4 and s[2] == " " and s[3] not in "-+@ \t":
        return HunkHeader("scope", scope=s[3:])
    return None


def indented_lexeme_code(line: str) -> Optional[str]:
    """§3.2 / §4.1: the code for a line that becomes a structural lexeme after removing leading
    spaces and tabs (E205 diff, E206 path header, E207 metadata, E302 option, E400 hunk header).

    Only lines that actually start with a space or tab qualify."""
    if not line or line[0] not in " \t":
        return None
    s = line.lstrip(" \t")
    if not s:
        return None
    if is_diff_command(s):
        return "E205"
    if is_path_header(s):
        return "E206"
    if is_metadata(s):
        return "E207"
    if option_match(s):
        return "E302"
    if s.startswith("@@"):
        return "E400"
    return None


def path_text_of_header(line: str) -> str:
    """The text after `--- ` / `+++ ` (the lexeme's space or tab), §6.3.4."""
    return line[4:]
