"""The parser state machine of §4.1 (PREAMBLE, HEADER, BODY, TRAILER).

Within each state the rules are tested in the order listed in §4.1; the first that applies
decides. "Immediately followed by" means the next line after skipping blank and comment lines
in PREAMBLE and HEADER, and the very next line in BODY.

The parser produces the block/hunk structure and every diagnostic the state machine itself
raises. Header semantics (§6) and hunk structure (§7) are validated afterward in
`validate.py`, on the finished structure.
"""
from __future__ import annotations

from typing import List, Optional

from . import lexemes as lx
from .diagnostics import Diagnostic, DiagnosticList, make_parse_diag
from .model import BLANK, CONTEXT, MARKER, MINUS, PLUS, Block, BodyElement, Document, HeaderLine, Hunk
from .options import (BOOLEAN_OPTIONS, KNOWN_OPTIONS, GlobalOptions, OptionLine, block_option_value,
                      parse_block_option_line, parse_version, version_supported)
from .paths import PathError, process_path_no_security, split_header_path

PREAMBLE = "PREAMBLE"
HEADER = "HEADER"
BODY = "BODY"
TRAILER = "TRAILER"
# Not a state of §4.1: the line after a trailing comment run (§12 item 5), which is by
# construction a block start line or a closing fence; it is processed as such.
AFTER_COMMENT_RUN = "AFTER_COMMENT_RUN"

SENTINEL = "sentinel"   # raw-element kind, removed in step (2) of the §3.1 processing order


class HostOptions:
    """Switches a host passes in addition to the document's options (§5.2 "tool-level switch")."""

    def __init__(self, check: bool = False, strict: bool = False, eol: Optional[str] = None) -> None:
        self.check = check
        self.strict = strict
        self.eol = eol


class EncodingProblem:
    """§1.3 / §10 E310 (§12 item 9): the patch is not valid UTF-8, or starts with a BOM."""

    def __init__(self, line_no: int, message: str) -> None:
        self.line_no = line_no
        self.message = message


def check_patch_encoding(data: bytes) -> Optional[EncodingProblem]:
    if data.startswith(b"\xef\xbb\xbf"):
        return EncodingProblem(1, "the patch starts with a UTF-8 BOM (lite-diff files are UTF-8 without BOM)")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        line_no = data.count(b"\n", 0, e.start) + 1
        return EncodingProblem(line_no, "the patch is not valid UTF-8 (byte 0x%02x at offset %d)"
                               % (data[e.start], e.start))
    return None


def split_patch_lines(data: bytes) -> List[str]:
    """§1.3 "Line splitting": LF or CRLF; the internal model uses LF (CR before LF stripped).

    The patch MUST be UTF-8 without BOM; a violation is E310 (`check_patch_encoding`). The text is
    still split (BOM dropped, undecodable bytes as U+FFFD) so that the parse phase can report the
    document's other errors too."""
    text = data.decode("utf-8", "replace")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()          # a final terminator does not start another line
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines]


class Parser:
    def __init__(self, lines: List[str], host: HostOptions,
                 encoding_problem: Optional[EncodingProblem] = None) -> None:
        self.lines = lines
        self.encoding_problem = encoding_problem
        self.host = host
        self.diags = DiagnosticList()
        self.opts = GlobalOptions()
        self.state = PREAMBLE
        self.doc = Document(lines=lines)
        self.block: Optional[Block] = None
        self.hunk: Optional[Hunk] = None
        self.fence_open = False
        self.seen_content = False        # a non-blank, non-comment line was seen (fence rule)
        self.options_final = False
        self.binary_payload = False      # inside a `GIT binary patch` payload (§4.1)
        self.skip_next = False           # second line of a body pair already consumed
        self.skip_to = -1                # lines of a trailing comment run already consumed (§12 item 5)

    # ------------------------------------------------------------------ helpers

    def emit(self, diag: Diagnostic, block: Optional[Block] = None, hunk: Optional[Hunk] = None) -> Diagnostic:
        if block is not None:
            diag.block = block.ordinal
        if hunk is not None:
            diag.hunk = hunk.ordinal
        self.diags.add(diag)
        if hunk is not None:
            hunk.errors.append(diag)
        elif block is not None:
            block.errors.append(diag)
        return diag

    def perr(self, code: str, message: str, i: int, block: Optional[Block] = None,
             hunk: Optional[Hunk] = None, hint: Optional[str] = None) -> Diagnostic:
        return self.emit(make_parse_diag(code, message, i + 1, self.lines[i], hint=hint), block, hunk)

    def next_significant(self, i: int) -> Optional[int]:
        """Index of the next line after i, skipping blank and comment lines (PREAMBLE/HEADER)."""
        j = i + 1
        while j < len(self.lines):
            ln = self.lines[j]
            if not lx.is_blank(ln) and not lx.is_comment(ln):
                return j
            j += 1
        return None

    def pair_follows(self, i: int) -> bool:
        """`--- ` at i immediately followed (PREAMBLE/HEADER sense) by `+++ `."""
        if not lx.is_minus_path_header(self.lines[i]):
            return False
        j = self.next_significant(i)
        return j is not None and lx.is_plus_path_header(self.lines[j])

    # ------------------------------------------------------------------ driver

    def parse(self) -> Document:
        if self.encoding_problem is not None:
            # §1.3 MUST, §10 E310 (§12 item 9). Parsing continues on the decoded text so that
            # the other parse errors of the document are reported as well.
            ep = self.encoding_problem
            ln = self.lines[ep.line_no - 1] if 0 < ep.line_no <= len(self.lines) else None
            self.emit(make_parse_diag("E310", ep.message, ep.line_no, ln))
        for i, line in enumerate(self.lines):
            if self.skip_next:
                self.skip_next = False
                continue
            if i < self.skip_to:
                continue
            if self.state == PREAMBLE:
                self.preamble_line(i, line)
            elif self.state == HEADER:
                self.header_line(i, line)
            elif self.state == BODY:
                self.body_line(i, line)
            elif self.state == AFTER_COMMENT_RUN:
                self.after_comment_run_line(i, line)
            else:
                self.trailer_line(i, line)
        # end of document → ends the hunk and the block
        self.finish_hunk()
        self.end_block()
        self.finalize_options()
        self.doc.diagnostics = self.diags.items
        self.doc.fence_open = self.fence_open
        return self.doc

    # ------------------------------------------------------------------ PREAMBLE (§4.1)

    def preamble_line(self, i: int, line: str) -> None:
        if lx.is_blank(line):
            return                                            # blank line → ignored
        if lx.is_comment(line):
            return                                            # `#…` → comment
        if lx.is_fence(line) and not self.seen_content:
            # a fence as the first non-blank, non-comment line → ignored with W300
            self.seen_content = True
            self.fence_open = True
            self.emit(make_parse_diag("W300", "Markdown fence before the first block ignored", i + 1, line))
            return
        self.seen_content = True
        om = lx.option_match(line)
        if om is not None:
            self.global_option(i, line, om[0], om[1])        # option grammar → global option
            return
        if lx.is_diff_command(line) or lx.is_metadata(line) or self.pair_follows(i):
            # block start; the line is processed by the HEADER rules
            self.finalize_options()
            self.start_block(i)
            self.state = HEADER
            self.header_line(i, line)
            return
        if lx.is_hunk_header_candidate(line):
            if lx.parse_hunk_header(line) is not None:
                self.perr("E306", "a hunk header cannot precede its block (no `---`/`+++` pair before it)", i)
            else:
                self.perr("E403", "malformed hunk header", i)
            return
        code = lx.indented_lexeme_code(line)
        if code is not None:
            self.perr(code, _INDENTED_MESSAGES[code], i)
            return
        self.perr("E306", "unexpected text before the first diff block", i,
                  hint="remove prose and mail headers; a lone `---` or `--- x` without `+++` is not a header")

    def global_option(self, i: int, line: str, name: str, value: Optional[str]) -> None:
        """§5 global option line."""
        if name not in KNOWN_OPTIONS:
            self.perr("E301", "unknown option --%s" % name, i)
            return
        if name in self.opts.lines:
            return                                            # duplicates are ignored (first wins)
        ol = OptionLine(i + 1, line, name, value)
        if name in BOOLEAN_OPTIONS:
            # §5 option grammar (§12 item 8): a boolean option is switched off with the value
            # `off`, as at block level (§5.5); any other value, or none, switches it on.
            self.opts.lines[name] = ol
            self.opts.flags[name] = block_option_value(value)
            return
        if name == "lite-diff":
            ver = parse_version(value)
            if ver is None:
                # §5 (§12 item 8): an invalid value for an option that takes one → E301.
                # A well-formed `<major>.<minor>` that is not supported is E308 below.
                self.perr("E301", "--lite-diff needs a version `<major>.<minor>`, got %r" % (value,), i)
                return
            if not version_supported(ver):
                self.perr("E308", "unsupported lite-diff version %r (this implementation supports 1.0 and 1.1)"
                          % (value,), i)
                return
            self.opts.lines[name] = ol
            self.opts.version = "%d.%d" % ver
            self.opts.profile_10 = ver == (1, 0)
            return
        if name == "strip":
            if value is None or not value.isdigit():
                self.perr("E301", "--strip needs a non-negative integer", i)
                return
            self.opts.lines[name] = ol
            self.opts.strip = int(value)
            return
        if name == "eol":
            if value not in ("lf", "crlf"):
                self.perr("E301", "--eol must be `lf` or `crlf`", i)     # §5.3
                return
            self.opts.lines[name] = ol
            self.opts.eol = value
            return
        if name == "default-root":
            if not value:
                self.perr("E301", "--default-root needs a value `@<root-name>`", i)
                return
            # §5.3: named roots exist only when the host declares a multi-root environment
            # (§12 item 29); this implementation is single-root → ignored with W301
            self.opts.lines[name] = ol
            self.emit(make_parse_diag("W301", "--default-root ignored in a single-root environment", i + 1, line))
            return

    def finalize_options(self) -> None:
        """Effective global options once the preamble is over (§5, §5.2)."""
        if self.options_final:
            return
        self.options_final = True
        o = self.opts
        if self.host.check:
            o.flags["check"] = True
        if self.host.strict:
            o.flags["strict"] = True
        if self.host.eol in ("lf", "crlf") and "eol" not in o.lines:
            o.eol = self.host.eol
        if o.profile_10:
            # §5 compatibility profile 1.0: implies --auto-rename and --first-match, disables --strict;
            # implied options never raise a conflict error such as E305 (§12 item 10)
            o.flags["auto-rename"] = True
            if not o.flags["first-match"]:
                o.implied_first_match = True
            o.flags["first-match"] = True
            o.flags["strict"] = False
        # §5.2 conflicts, located at the later of the two lines (§8.6)
        if o.flag("apply-all-matches") and o.flag("first-match") and not o.implied_first_match:
            self.conflict("E305", "--apply-all-matches and --first-match are mutually exclusive",
                          o.lines.get("apply-all-matches"), o.lines.get("first-match"))
        if o.flag("lenient") and o.flag("strict"):
            self.conflict("E307", "--lenient cannot be combined with --strict",
                          o.lines.get("lenient"), o.lines.get("strict"))
        # from here on, warnings listed in §5.2 are escalated when they are added (W401 can only
        # occur in a body, i.e. after this point)
        self.diags.strict = o.flag("strict")

    def conflict(self, code: str, message: str, a: Optional[OptionLine], b: Optional[OptionLine]) -> None:
        lines = [x for x in (a, b) if x is not None]
        if lines:
            later = max(lines, key=lambda x: x.line_no)
            self.emit(make_parse_diag(code, message, later.line_no, later.text))
        else:   # both set by the host
            self.emit(Diagnostic(code=code, message=message + " (host settings)"))

    # ------------------------------------------------------------------ blocks

    def start_block(self, i: int, after_body_pair: bool = False) -> Block:
        b = Block(ordinal=len(self.doc.blocks) + 1, start_line=i + 1, start_text=self.lines[i],
                  started_by_pair_after_body=after_body_pair)
        self.doc.blocks.append(b)
        self.block = b
        return b

    def end_header(self, b: Block) -> None:
        """End-of-header check of §4.1: a `---` without `+++` or vice versa → E200."""
        if b.header_done:
            return
        b.header_done = True
        if b.minus and not b.plus:
            hl = b.minus[0]
            self.emit(make_parse_diag("E200", "`---` without `+++`", hl.line_no, hl.text), b)
        elif b.plus and not b.minus:
            hl = b.plus[0]
            self.emit(make_parse_diag("E200", "`+++` without `---`", hl.line_no, hl.text), b)

    def end_block(self) -> None:
        if self.block is not None:
            self.end_header(self.block)
        self.block = None
        self.binary_payload = False

    def new_block_from(self, i: int, after_body_pair: bool = False) -> Block:
        self.finish_hunk()
        self.end_block()
        return self.start_block(i, after_body_pair)

    # ------------------------------------------------------------------ HEADER (§4.1)

    def header_line(self, i: int, line: str) -> None:
        b = self.block
        assert b is not None
        if self.binary_payload:
            # `GIT binary patch` payload: skipped up to the next diff command line, metadata
            # keyword line, or `--- `/`+++ ` pair
            if lx.is_diff_command(line) or lx.is_metadata(line) or self.pair_follows(i):
                self.binary_payload = False
            else:
                return
        if lx.is_diff_command(line):
            if not b.is_empty:
                b = self.new_block_from(i)                     # ends the current block
            hl = HeaderLine(i + 1, line, line[len("diff "):])
            if lx.is_diff_git(line):
                b.diff_git = HeaderLine(i + 1, line, line[len("diff --git "):])
            else:
                b.diff_command = hl
            return
        if self.pair_follows(i):
            if b.holds_plus:
                b = self.new_block_from(i)                     # hunk-less block followed by the next one
                self.record_path_header(b, i, line)
                return
            pair = b.completed_pair
            if pair is not None:
                # §4.1 (§12 item 1): the pair belongs to this rename/copy header when its `---` path
                # (after §6.3.1 processing) equals `from`; otherwise it starts a new block.
                from_line = (b.rename_from if pair == "rename" else b.copy_from)[0]
                from_path = process_path_no_security(from_line.value, "operation", self.opts.strip)
                minus_raw = _header_path_raw(line)
                minus_path = (process_path_no_security(minus_raw, "header", self.opts.strip)
                              if minus_raw is not None else None)
                if minus_path is None or minus_path != from_path:
                    b = self.new_block_from(i)
                self.record_path_header(b, i, line)
                return
        if lx.is_operation_opening(line) and (b.holds_plus or b.completed_pair is not None):
            b = self.new_block_from(i)
            self.record_metadata(b, i, line)
            return
        code = lx.indented_lexeme_code(line)
        if code is not None:
            # tested before the body-looking rule (§12 item 1): an indented `@@` after `+++` is E400
            self.perr(code, _INDENTED_MESSAGES[code], i, b)
            return
        if (b.holds_plus and line[:1] in (" ", "+", "-") and not lx.is_metadata(line)
                and not lx.is_plus_path_header(line)):
            # body-looking line after `+++` → E404 once per block; the rest are skipped
            self.e404(b, i)
            return
        if line.startswith("GIT binary patch"):
            self.record_metadata(b, i, line)
            self.binary_payload = True
            return
        if lx.is_path_header(line):
            self.record_path_header(b, i, line)
            return
        if lx.is_metadata(line):
            self.record_metadata(b, i, line)
            return
        if lx.is_comment(line):
            return
        if lx.is_hunk_header_candidate(line):
            hh = lx.parse_hunk_header(line)
            if hh is None:
                self.perr("E403", "malformed hunk header", i, b, hint=_E403_HINT)
                return                                         # a malformed one does not change state
            self.end_header(b)
            self.start_hunk(i, line, hh)
            self.state = BODY
            return
        if lx.is_blank(line):
            return
        if lx.option_match(line) is not None:
            self.perr("E300", "global options are allowed only before the first block; "
                              "use `option <name>` for a block-level option", i, b)
            return
        if line[:1] in (" ", "-", "+") or line.startswith("..."):
            self.e404(b, i)                                    # header without `+++` yet
            return
        if lx.is_fence(line) and self.fence_open:
            self.end_block()
            self.state = TRAILER
            return
        # any other line → ignored; W200 (MAY)
        self.emit(make_parse_diag("W200", "unrecognized header line ignored", i + 1, line), b)

    def e404(self, b: Block, i: int) -> None:
        if b.e404_reported:
            return
        b.e404_reported = True
        hint = None
        if b.started_by_pair_after_body:
            hint = ("this block's header is a `---`/`+++` pair that ended the previous hunk body: "
                    "a hunk header may be missing here, or the pair may be a `-- `/`++ ` comment edit (§7.2)")
        self.perr("E404", "body line before hunk header (missing `@@`?)", i, b, hint=hint)

    def record_path_header(self, b: Block, i: int, line: str) -> None:
        hl = HeaderLine(i + 1, line, lx.path_text_of_header(line))
        if lx.is_minus_path_header(line):
            b.minus.append(hl)
            if len(b.minus) > 1:
                self.perr("E200", "second `---` path header in one block header", i, b)
        else:
            b.plus.append(hl)
            if len(b.plus) > 1:
                self.perr("E200", "second `+++` path header in one block header", i, b)

    def record_metadata(self, b: Block, i: int, line: str) -> None:
        kw = lx.metadata_keyword(line)
        value = line[len(kw):] if kw else ""
        hl = HeaderLine(i + 1, line, value)
        if kw == "rename from ":
            b.rename_from.append(hl)
        elif kw == "rename to ":
            b.rename_to.append(hl)
        elif kw == "copy from ":
            b.copy_from.append(hl)
        elif kw == "copy to ":
            b.copy_to.append(hl)
        elif kw == "new file mode ":
            b.new_file_mode = hl
        elif kw == "deleted file mode ":
            b.deleted_file_mode = hl
        elif kw == "old mode ":
            b.old_mode = hl
        elif kw == "new mode ":
            b.new_mode = hl
        elif kw == "index ":
            b.index_line = hl
        elif kw in ("Binary files ", "GIT binary patch"):
            if b.binary_line is None:
                b.binary_line = hl
        elif kw == "option ":
            name, val = parse_block_option_line(line)
            b.option_lines.append(OptionLine(i + 1, line, name, val))
        # similarity index / dissimilarity index → ignored metadata

    # ------------------------------------------------------------------ hunks / BODY (§4.1, §7.2)

    def start_hunk(self, i: int, line: str, hh: lx.HunkHeader) -> None:
        b = self.block
        assert b is not None
        self.hunk = Hunk(ordinal=len(b.hunks) + 1, header_line_no=i + 1, header_text=line, header=hh)
        b.hunks.append(self.hunk)

    def finish_hunk(self) -> None:
        """§3.1 processing order: (2) sentinels removed after recording their presence;
        (3) trailing blank lines stripped."""
        h = self.hunk
        self.hunk = None
        if h is None:
            return
        raw = h.raw_elements
        elements = [e for e in raw if e.kind != SENTINEL]
        t = 0
        while elements and elements[-1].kind == BLANK:
            elements.pop()
            t += 1
        h.elements = elements
        h.trailing_blanks = t
        self.record_sentinels(h)

    def record_sentinels(self, h: Hunk) -> None:
        """§3.1 "Body lines" (§12 item 24): which body line each sentinel follows.

        - after a `+` line → new side; after a `-` line → old side;
        - after a context (or blank) line that is the hunk's last body line → new side (and old side:
          an unchanged last line is the last line of both sides, as in `git diff`);
        - after a context line that is not the last body line → old side.
        A sentinel decides or asserts something only when it follows the **last** line of its side
        (§1.3 "Final terminator"); any other sentinel (also one before the first body line or after
        a `...` marker) is misplaced and gives W419 in the match phase. Trailing blank lines that
        step (3) stripped are not body lines: a sentinel after them follows the line before them."""
        if not h.sentinel_lines:
            return
        kept = {id(e) for e in h.elements}
        new_side = [e for e in h.elements if e.kind in (CONTEXT, BLANK, PLUS)]
        old_side = [e for e in h.elements if e.kind in (CONTEXT, BLANK, MINUS)]
        last_new = new_side[-1] if new_side else None
        last_old = old_side[-1] if old_side else None
        last_el = h.elements[-1] if h.elements else None
        raw = h.raw_elements
        for r, s in enumerate(raw):
            if s.kind != SENTINEL:
                continue
            prev = next((raw[k] for k in range(r - 1, -1, -1)
                         if raw[k].kind != SENTINEL and id(raw[k]) in kept), None)
            placed = False
            if prev is None or prev.kind == MARKER:
                pass
            elif prev.kind == PLUS:
                if prev is last_new:
                    h.sentinel_new_end = True
                    placed = True
            elif prev.kind == MINUS:
                if prev is last_old:
                    h.sentinel_old_end = True
                    placed = True
            elif prev is last_el:                       # context / blank, last body line
                h.sentinel_new_end = True
                h.sentinel_old_end = True
                placed = True
            elif prev is last_old:                      # context followed by `+` lines only
                h.sentinel_old_end = True
                placed = True
            if not placed:
                h.sentinel_misplaced.append(s.line_no)
        # create blocks (§6.4.5): the new-side sentinel after the last `+` line
        h.sentinel_after_last_plus = h.sentinel_new_end and last_new is not None and last_new.kind == PLUS

    def body_line(self, i: int, line: str) -> None:
        b, h = self.block, self.hunk
        assert b is not None and h is not None
        if lx.is_hunk_header_candidate(line):
            hh = lx.parse_hunk_header(line)
            if hh is None:
                self.perr("E403", "malformed hunk header", i, b, h, hint=_E403_HINT)
                return
            self.finish_hunk()
            self.start_hunk(i, line, hh)
            return
        if lx.is_diff_command(line) or lx.is_metadata(line):
            self.new_block_from(i)
            self.state = HEADER
            self.header_line(i, line)
            return
        if lx.is_minus_path_header(line) and i + 1 < len(self.lines) and lx.is_plus_path_header(self.lines[i + 1]):
            nxt = self.lines[i + 2] if i + 2 < len(self.lines) else None
            if (nxt is not None and (nxt[:1] in (" ", "-", "+") or nxt.startswith("..."))
                    and not lx.is_path_header(nxt) and not lx.is_metadata(nxt)
                    and not lx.is_hunk_header_candidate(nxt)):
                # §7.2 body-pair rule: two body lines, W401 naming the `---` line
                self.emit(make_parse_diag(
                    "W401", "`--- `/`+++ ` pair inside a hunk body treated as two body lines "
                            "(deletion of `-%s`, insertion of `+%s`); if a new block was intended here, "
                            "its hunk header is missing and its body lines were read as part of this hunk"
                            % (line[1:], self.lines[i + 1][1:]), i + 1, line), b, h)
                h.raw_elements.append(BodyElement(MINUS, line[1:], i + 1, line))
                h.raw_elements.append(BodyElement(PLUS, self.lines[i + 1][1:], i + 2, self.lines[i + 1]))
                self.skip_next = True
                return
            self.new_block_from(i, after_body_pair=True)
            self.state = HEADER
            self.header_line(i, line)
            return
        if lx.is_fence(line) and self.fence_open:
            self.finish_hunk()
            self.end_block()
            self.state = TRAILER
            return
        if line.startswith("#"):
            # §4.1 BODY (§12 item 5): look ahead over the following `#` and blank lines
            j = i + 1
            while j < len(self.lines) and (lx.is_blank(self.lines[j]) or lx.is_comment(self.lines[j])):
                j += 1
            if j >= len(self.lines) or self.is_block_start(j) or (lx.is_fence(self.lines[j]) and self.fence_open):
                # trailing comment run (§3.1 "Comment"): ends this hunk and the block; ignored
                self.finish_hunk()
                self.end_block()
                self.state = AFTER_COMMENT_RUN
                self.skip_to = j
                return
            # otherwise E401 (§3.1, §7.2); profile 1.0 drops it (§5), see body_element
        self.body_element(i, line, b, h)

    def is_block_start(self, j: int) -> bool:
        """§3.1 "Comment": a block start line is a diff command line, a metadata keyword line, or a
        `--- `/`+++ ` pair. After a comment run the body has ended, so the pair is taken in the
        PREAMBLE/HEADER sense of "immediately followed" (blank and comment lines skipped) and the
        body-pair rule of §7.2 does not apply."""
        line = self.lines[j]
        return lx.is_diff_command(line) or lx.is_metadata(line) or self.pair_follows(j)

    def after_comment_run_line(self, i: int, line: str) -> None:
        """The line after a trailing comment run: a block start (→ HEADER) or a closing fence (→ TRAILER)."""
        if lx.is_fence(line) and self.fence_open and not self.is_block_start(i):
            self.state = TRAILER
            return
        self.start_block(i)
        self.state = HEADER
        self.header_line(i, line)

    def body_element(self, i: int, line: str, b: Block, h: Hunk) -> None:
        """§7.2: body line, sentinel, or E401."""
        if line == "":
            h.raw_elements.append(BodyElement(BLANK, "", i + 1, line))
        elif line[0] == " ":
            h.raw_elements.append(BodyElement(CONTEXT, line[1:], i + 1, line))
        elif line[0] == "-":
            h.raw_elements.append(BodyElement(MINUS, line[1:], i + 1, line))
        elif line[0] == "+":
            h.raw_elements.append(BodyElement(PLUS, line[1:], i + 1, line))
        elif lx.is_marker(line):
            h.raw_elements.append(BodyElement(MARKER, "", i + 1, line))
        elif lx.is_sentinel(line):
            h.raw_elements.append(BodyElement(SENTINEL, "", i + 1, line))
            h.sentinel_lines.append(i + 1)
        elif line[0] == "#" and self.opts.profile_10:
            return                                   # §5 profile 1.0: a `#` line in a body is a dropped comment
        else:
            self.perr("E401", "invalid line in hunk body", i, b, h, hint=_e401_hint(line))

    # ------------------------------------------------------------------ TRAILER (§4.1)

    def trailer_line(self, i: int, line: str) -> None:
        if lx.is_blank(line):
            return
        if lx.is_hunk_header_candidate(line) and lx.parse_hunk_header(line) is None:
            self.perr("E403", "malformed hunk header", i)
            return
        self.perr("E306", "unexpected text outside the diff (after the closing fence)", i)


def _header_path_raw(line: str) -> Optional[str]:
    try:
        return split_header_path(lx.path_text_of_header(line))
    except PathError:
        return None


_INDENTED_MESSAGES = {
    "E205": "`diff` header not in the first position",
    "E206": "`---`/`+++` path header not in the first position",
    "E207": "header metadata line not in the first position",
    "E302": "global option not in the first position",
    "E400": "hunk header `@@` not in the first position",
}

_E403_HINT = ("use exactly `@@`, `@@ BOF`, `@@ EOF`, `@@ -a[,m] +b[,n] @@ [section]`, "
              "or `@@ <scope text>` (one space, text not starting with `-`, `+`, `@` or whitespace)")


def _e401_hint(line: str) -> str:
    c = line[0]
    if c == "\t":
        return "a tab in the first position is not a prefix; a context line for a tab-indented file line is ` <tab>…`"
    if c == "#":
        return ("comments are not allowed inside a hunk body (only a run of `#` lines directly before the next "
                "block, the closing fence or the end of the patch); if this is a file line, add the prefix (` #…`)")
    if c == "`":
        return "a backtick line is a fence only when a fence was opened before the first block"
    if c == "\\":
        return "only `\\ ` (backslash + space) is the sentinel; prefix the file line (` \\…`)"
    if line.startswith("..."):
        return "`...` is a marker only when nothing but whitespace follows it"
    return ("every body line needs a prefix (` `, `-`, `+`); text after the last hunk is read as hunk lines — "
            "remove prose or put it after the closing fence")
