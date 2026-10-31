"""Global options (§5) and block-level options (§5.5).

`GlobalOptions` holds the effective document-wide values after the preamble has been read
(including the `--lite-diff 1.0` compatibility profile and host switches). `MatchOptions`
is the per-block view used by the matcher: the global values overridden by `option` lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

SUPPORTED_MAJOR = 1
SUPPORTED_MINOR = 1          # this implementation is v1.1; 1.0 selects the compatibility profile
DEFAULT_VERSION = "1.1"      # §5 "Without the marker ... the newest version the implementation supports"

# Boolean options (§4 diagram, §5.1, §5.2).
BOOLEAN_OPTIONS = (
    "ignore-space-at-eol", "ignore-space-change", "ignore-blank-lines", "ignore-all-space",
    "apply-all-matches", "first-match", "auto-rename", "check", "strict",
    "indent-shift", "lenient", "skip-applied",
)
# Options with a value.
VALUE_OPTIONS = ("lite-diff", "strip", "eol", "default-root")
KNOWN_OPTIONS = BOOLEAN_OPTIONS + VALUE_OPTIONS

# §5.5 allowed at block level, `ignore-space-at-eol` included as a no-op (§12 item 12).
BLOCK_ALLOWED = (
    "ignore-space-change", "ignore-blank-lines", "ignore-all-space", "apply-all-matches",
    "first-match", "indent-shift", "lenient", "skip-applied", "ignore-space-at-eol",
)
# §5.5 not allowed at block level → E309.
BLOCK_FORBIDDEN = ("lite-diff", "strict", "check", "auto-rename", "strip", "eol", "default-root")

# The options that matching depends on (block-overridable).
MATCH_FLAGS = (
    "ignore-space-change", "ignore-blank-lines", "ignore-all-space", "apply-all-matches",
    "first-match", "indent-shift", "lenient", "skip-applied",
)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


@dataclass
class OptionLine:
    """An option as written: global `--name value` or block-level `option name value`."""

    line_no: int
    text: str
    name: str
    value: Optional[str]


@dataclass
class GlobalOptions:
    """Effective document-wide options (§5)."""

    flags: Dict[str, bool] = field(default_factory=lambda: {n: False for n in BOOLEAN_OPTIONS})
    version: str = DEFAULT_VERSION
    strip: Optional[int] = None       # §5.3 --strip N (None: letter-prefix rule of §6.3.5)
    eol: str = "lf"                   # §5.3 --eol lf|crlf (§12 item 22: default LF)
    default_root: Optional[str] = None
    # where each option was set (for the location of E305/E307, §8.6 "the later of the two lines")
    lines: Dict[str, OptionLine] = field(default_factory=dict)
    profile_10: bool = False          # §5 compatibility profile 1.0 (§12 item 10)
    # first-match implied by the 1.0 profile is not an explicit option: implied options never raise a
    # conflict error such as E305 (§5, §12 item 10)
    implied_first_match: bool = False

    def flag(self, name: str) -> bool:
        return self.flags.get(name, False)

    @property
    def eol_bytes(self) -> bytes:
        return b"\r\n" if self.eol == "crlf" else b"\n"

    def to_json(self) -> Dict[str, object]:
        out: Dict[str, object] = {}
        for name in BOOLEAN_OPTIONS:
            out[name] = self.flags[name]
        out["lite-diff"] = self.version
        out["strip"] = self.strip
        out["eol"] = self.eol
        if self.default_root is not None:
            out["default-root"] = self.default_root
        return out


@dataclass
class MatchOptions:
    """Effective options of one block (§5.5): global values overridden by `option` lines."""

    ignore_space_change: bool = False
    ignore_blank_lines: bool = False
    ignore_all_space: bool = False
    apply_all_matches: bool = False
    first_match: bool = False
    indent_shift: bool = False
    lenient: bool = False
    skip_applied: bool = False

    @staticmethod
    def from_flags(flags: Dict[str, bool]) -> "MatchOptions":
        return MatchOptions(
            ignore_space_change=flags.get("ignore-space-change", False),
            ignore_blank_lines=flags.get("ignore-blank-lines", False),
            ignore_all_space=flags.get("ignore-all-space", False),
            apply_all_matches=flags.get("apply-all-matches", False),
            first_match=flags.get("first-match", False),
            indent_shift=flags.get("indent-shift", False),
            lenient=flags.get("lenient", False),
            skip_applied=flags.get("skip-applied", False),
        )

    def to_json(self) -> Dict[str, bool]:
        return {
            "ignore-space-change": self.ignore_space_change,
            "ignore-blank-lines": self.ignore_blank_lines,
            "ignore-all-space": self.ignore_all_space,
            "apply-all-matches": self.apply_all_matches,
            "first-match": self.first_match,
            "indent-shift": self.indent_shift,
            "lenient": self.lenient,
            "skip-applied": self.skip_applied,
        }

    def with_space_change(self) -> "MatchOptions":
        """§8.2 step 5 level (c): `--ignore-space-change` comparison."""
        return replace(self, ignore_space_change=True)

    def with_all_space(self) -> "MatchOptions":
        """§8.6 E410: "whether the anchor would match ... under --ignore-all-space"."""
        return replace(self, ignore_all_space=True)


def parse_version(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    m = _VERSION_RE.match(value)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def version_supported(ver: Tuple[int, int]) -> bool:
    """§5 E308: unsupported major version, or a higher minor of the same major."""
    major, minor = ver
    return major == SUPPORTED_MAJOR and minor <= SUPPORTED_MINOR


def block_option_value(value: Optional[str]) -> bool:
    """§5.5 and §5 for global options (§12 item 8): `off` switches a boolean option
    off; any other value, or none, on."""
    return value != "off"


def parse_block_option_line(text: str) -> Tuple[str, Optional[str]]:
    """`option <name>[ <value>]` → (name, value)."""
    rest = text[len("option "):]
    if " " in rest:
        name, value = rest.split(" ", 1)
        return name, value
    return rest, None


def effective_block_options(global_opts: GlobalOptions, option_lines: List[OptionLine]) -> MatchOptions:
    """§5.5: a later `option` line for the same name wins."""
    flags = {name: global_opts.flag(name) for name in MATCH_FLAGS}
    for ol in option_lines:
        if ol.name in MATCH_FLAGS:
            flags[ol.name] = block_option_value(ol.value)
    return MatchOptions.from_flags(flags)
