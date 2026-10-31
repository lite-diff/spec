"""Diagnostics: codes, severities, locations and visible-whitespace rendering (§8.6, §10, Appendix B).

A diagnostic is plain data. Where it is attached (patch line, block, hunk) follows the
"location" rule of §8.6: parse-phase codes carry the patch line and the offending line,
file-system codes the block ordinal, matching codes the block and hunk ordinals.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ERROR = "error"
WARNING = "warning"

# §5.2 --strict: these warnings are treated as errors (§12 item 21; W416 cannot occur under --strict).
# W410 is not escalated on an exact hit (§12 item 21): the engine
# adds that diagnostic with `escalate=False`.
STRICT_ESCALATED = frozenset({"W401", "W410", "W412", "W413", "W417", "W418", "W511"})

# §5.2: W401 is the only parse-phase warning that --strict escalates.
PARSE_PHASE_WARNINGS = frozenset({"W200", "W300", "W301", "W401"})


@dataclass
class Diagnostic:
    """One error or warning (Appendix B `diagnostic`)."""

    code: str
    message: str
    patch_line: Optional[int] = None      # 1-based patch line (parse-phase codes, §8.6)
    patch_text: Optional[str] = None      # offending line, whitespace made visible
    block: Optional[int] = None           # 1-based block ordinal
    hunk: Optional[int] = None            # 1-based hunk ordinal within the block
    escalated: bool = False               # warning treated as an error under --strict (§5.2)
    hint: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)  # searchStart, cursor, bestCandidate, candidates, ...

    @property
    def is_error(self) -> bool:
        return self.code.startswith("E") or self.escalated

    @property
    def severity(self) -> str:
        return ERROR if self.is_error else WARNING

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.escalated:
            out["escalated"] = True
        if self.patch_line is not None:
            out["patchLine"] = self.patch_line
        if self.patch_text is not None:
            out["patchText"] = self.patch_text
        if self.block is not None:
            out["block"] = self.block
        if self.hunk is not None:
            out["hunk"] = self.hunk
        for key, value in self.extra.items():
            out[key] = value
        if self.hint is not None:
            out["hint"] = self.hint
        return out


# --------------------------------------------------------------------------------------------
# Visible whitespace (§8.6 "Diagnostic content"): `·` for space, `→` for tab, a marker for
# trailing whitespace, escape sequences for every non-ASCII whitespace or invisible code point.
# --------------------------------------------------------------------------------------------

TRAILING_MARKER = "¶"  # appended when the line ends with whitespace


def _is_invisible(ch: str) -> bool:
    if ch in (" ", "\t"):
        return False
    cat = unicodedata.category(ch)
    # Zs: space separators (NBSP, thin space, ...); Zl/Zp: line/paragraph separators;
    # Cf: format characters (zero-width space/joiners, BOM, soft hyphen); Cc: control characters.
    return cat in ("Zs", "Zl", "Zp", "Cf", "Cc")


def visible(text: str) -> str:
    """Render a line with whitespace made visible (§8.6)."""
    out = []
    for ch in text:
        if ch == " ":
            out.append("·")
        elif ch == "\t":
            out.append("→")
        elif ch == "\udcff" or ("\udc80" <= ch <= "\udcff"):
            # undecodable byte kept by surrogateescape (target files are bytes, §1.3)
            out.append("\\x%02x" % (ord(ch) - 0xDC00))
        elif _is_invisible(ch):
            code = ord(ch)
            out.append("\\u%04X" % code if code <= 0xFFFF else "\\U%08X" % code)
        else:
            out.append(ch)
    if text and text[-1] in (" ", "\t"):
        out.append(TRAILING_MARKER)
    return "".join(out)


def visible_bytes(data: bytes) -> str:
    """Render a target-file line (bytes, not necessarily UTF-8) visibly."""
    return visible(data.decode("utf-8", "surrogateescape"))


def make_parse_diag(code: str, message: str, line_no: Optional[int], line_text: Optional[str],
                    block: Optional[int] = None, hunk: Optional[int] = None,
                    hint: Optional[str] = None) -> Diagnostic:
    """A parse-phase diagnostic located at a patch line (§8.6 location rule)."""
    return Diagnostic(code=code, message=message, patch_line=line_no,
                      patch_text=visible(line_text) if line_text is not None else None,
                      block=block, hunk=hunk, hint=hint)


class DiagnosticList:
    """Ordered collection of diagnostics with --strict escalation (§5.2)."""

    def __init__(self, strict: bool = False) -> None:
        self.items: List[Diagnostic] = []
        self.strict = strict

    def add(self, diag: Diagnostic, escalate: bool = True) -> Diagnostic:
        if escalate and self.strict and diag.code in STRICT_ESCALATED:
            diag.escalated = True
        self.items.append(diag)
        return diag

    def has_errors(self) -> bool:
        return any(d.is_error for d in self.items)
