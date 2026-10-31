"""Parse results: document, blocks, header lines, hunks and body elements (§3.1, §4.1, §6, §7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .diagnostics import Diagnostic
from .lexemes import HunkHeader
from .options import MatchOptions, OptionLine

# Body element kinds (§3.1 "Body lines", §7.2 table).
CONTEXT = "context"    # ` ` prefix
BLANK = "blank"        # a blank body line: context of an empty line
MINUS = "minus"        # `-` prefix
PLUS = "plus"          # `+` prefix
MARKER = "marker"      # `...`

ANCHOR_KINDS = (CONTEXT, BLANK, MINUS, MARKER)  # §3.1 "Anchor element"


@dataclass
class BodyElement:
    kind: str
    content: str          # text after the prefix ("" for BLANK and MARKER)
    line_no: int          # 1-based patch line
    raw: str              # the patch line as written

    @property
    def is_anchor(self) -> bool:
        return self.kind in ANCHOR_KINDS

    @property
    def is_blank_context(self) -> bool:
        """A blank body line, or a context line with empty (or whitespace-only) content.

        §5.1 removes "blank context anchor elements (a blank body line or ` ` with empty content)"
        under --ignore-blank-lines. A whitespace-only context line is included: trailing
        whitespace is never significant (§1.3), so it matches exactly the same file lines."""
        if self.kind == BLANK:
            return True
        return self.kind == CONTEXT and self.content.strip(" \t") == ""


@dataclass
class Hunk:
    ordinal: int
    header_line_no: int
    header_text: str
    header: HunkHeader
    raw_elements: List[BodyElement] = field(default_factory=list)  # before sentinel/trailing-blank processing
    elements: List[BodyElement] = field(default_factory=list)      # body after §3.1 processing order
    sentinel_after_last_plus: bool = False   # §3.1 "Body lines", needed by §6.4.5
    # §3.1 "Body lines" / §1.3 "Final terminator" (§12 item 24)
    sentinel_new_end: bool = False           # sentinel after the last line of the new side
    sentinel_old_end: bool = False           # sentinel after the last line of the old side
    sentinel_misplaced: List[int] = field(default_factory=list)   # patch lines of other sentinels (W419)
    trailing_blanks: int = 0                 # `t` of §8.2 step 6
    sentinel_lines: List[int] = field(default_factory=list)
    errors: List[Diagnostic] = field(default_factory=list)          # parse diagnostics raised in this hunk

    @property
    def anchors(self) -> List[BodyElement]:
        return [e for e in self.elements if e.is_anchor]

    @property
    def has_plus(self) -> bool:
        return any(e.kind == PLUS for e in self.elements)

    @property
    def has_minus(self) -> bool:
        return any(e.kind == MINUS for e in self.elements)

    @property
    def has_marker(self) -> bool:
        return any(e.kind == MARKER for e in self.elements)

    @property
    def header_json(self) -> str:
        return self.header.kind


@dataclass
class HeaderLine:
    """A recorded header line: keyword (e.g. "rename from "), the value, and its patch line."""

    line_no: int
    text: str
    value: str


@dataclass
class Block:
    ordinal: int
    start_line: int
    start_text: str
    started_by_pair_after_body: bool = False   # §8.6 E404/E608 hint: header pair that ended a hunk body
    diff_git: Optional[HeaderLine] = None
    diff_command: Optional[HeaderLine] = None
    minus: List[HeaderLine] = field(default_factory=list)   # `---` lines (value = text after the lexeme)
    plus: List[HeaderLine] = field(default_factory=list)    # `+++` lines
    rename_from: List[HeaderLine] = field(default_factory=list)
    rename_to: List[HeaderLine] = field(default_factory=list)
    copy_from: List[HeaderLine] = field(default_factory=list)
    copy_to: List[HeaderLine] = field(default_factory=list)
    new_file_mode: Optional[HeaderLine] = None
    deleted_file_mode: Optional[HeaderLine] = None
    old_mode: Optional[HeaderLine] = None
    new_mode: Optional[HeaderLine] = None
    index_line: Optional[HeaderLine] = None
    binary_line: Optional[HeaderLine] = None     # `Binary files ...` or `GIT binary patch` (W601)
    option_lines: List[OptionLine] = field(default_factory=list)
    hunks: List[Hunk] = field(default_factory=list)
    errors: List[Diagnostic] = field(default_factory=list)   # parse diagnostics of this block (all phases of parsing)
    warnings: List[Diagnostic] = field(default_factory=list)
    e404_reported: bool = False                # §4.1: E404 once per block
    header_done: bool = False                  # end-of-header E200 check performed

    # filled by header validation (§6.3, §6.4)
    source: Optional[str] = None       # canonical path ('/'-separated, NFC) or "/dev/null"
    target: Optional[str] = None
    operation: str = "edit"            # edit / create / delete / rename / copy
    skipped_code: Optional[str] = None  # W601 / W603 when the block is skipped (§6.4.4 step 1)
    match_options: MatchOptions = field(default_factory=MatchOptions)

    @property
    def holds_plus(self) -> bool:
        return bool(self.plus)

    @property
    def completed_pair(self) -> Optional[str]:
        """"rename" or "copy" when the header holds a completed from/to pair (§4.1)."""
        if self.rename_from and self.rename_to:
            return "rename"
        if self.copy_from and self.copy_to:
            return "copy"
        return None

    @property
    def is_empty(self) -> bool:
        return (self.diff_git is None and self.diff_command is None and not self.minus and not self.plus
                and not self.rename_from and not self.rename_to and not self.copy_from and not self.copy_to
                and self.new_file_mode is None and self.deleted_file_mode is None
                and self.old_mode is None and self.new_mode is None and self.index_line is None
                and self.binary_line is None and not self.option_lines)

    @property
    def has_parse_error(self) -> bool:
        if any(d.is_error for d in self.errors):
            return True
        return any(any(d.is_error for d in h.errors) for h in self.hunks)


@dataclass
class Document:
    lines: List[str]
    blocks: List[Block] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)   # every diagnostic, in order of discovery
    fence_open: bool = False
