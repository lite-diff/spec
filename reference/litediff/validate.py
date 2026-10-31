"""Parse-phase validation of each block (§6.4.4 steps 1–4).

Step 1: binary (W601) / non-regular mode (W603) → block skipped.
Step 2: header structure and path consistency (§6.3.2: E200, E202, E209, E608), block-level
        options (§5.5: E301, E305, E307, E309), operation validity (§6.4.2: E604–E606).
Step 3: path syntax (§6.3.3: E100–E102; §5.3: E104), and quoting (E203, E204). (E201 is reserved,
        §12 item 29: the `<prefix>:` scheme no longer exists.)
Step 4: hunk structure (§7, §6.4.5: E404, E411, E412, E415–E417, E5xx, E304).

All failures of steps 2–4 are reported (a block may accumulate several parse errors);
within the ordered list of §6.3.2 only the first failure is reported.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .diagnostics import Diagnostic, DiagnosticList, make_parse_diag
from .model import MARKER, MINUS, PLUS, Block, HeaderLine, Hunk
from .options import (BLOCK_ALLOWED, BLOCK_FORBIDDEN, GlobalOptions, OptionLine,
                      effective_block_options)
from .paths import DEV_NULL, PathError, process_path, split_diff_git, split_header_path

NON_REGULAR_MODES = ("120000", "160000")   # §6.4.1 symbolic link / submodule


class BlockValidator:
    def __init__(self, block: Block, opts: GlobalOptions, diags: DiagnosticList) -> None:
        self.b = block
        self.opts = opts
        self.diags = diags
        self.reported: Set[Tuple[str, str]] = set()

    # ------------------------------------------------------------------ helpers

    def err(self, code: str, message: str, line: Optional[HeaderLine] = None, hunk: Optional[Hunk] = None,
            line_no: Optional[int] = None, line_text: Optional[str] = None, hint: Optional[str] = None) -> Diagnostic:
        if line is not None:
            line_no, line_text = line.line_no, line.text
        d = make_parse_diag(code, message, line_no, line_text, block=self.b.ordinal,
                            hunk=hunk.ordinal if hunk else None, hint=hint)
        self.diags.add(d)
        if hunk is not None:
            hunk.errors.append(d)
        else:
            self.b.errors.append(d)
        return d

    def block_start_err(self, code: str, message: str, hint: Optional[str] = None) -> Diagnostic:
        """Block-level code with no single line → the block start line (§8.6)."""
        return self.err(code, message, line_no=self.b.start_line, line_text=self.b.start_text, hint=hint)

    # ------------------------------------------------------------------ entry

    def run(self) -> None:
        b = self.b
        b.match_options = effective_block_options(self.opts, b.option_lines)
        if self.step1_skip():
            self.extract_paths(report=False)
            # §6.4.4 step 1 (§12 item 31): the `operation` reported for a skipped block is the one
            # its header indicators imply, not a placeholder
            b.operation = self.implied_operation()
            return
        paths_ok = self.extract_paths(report=True)
        self.check_block_options()
        if paths_ok:
            self.check_path_consistency()
        self.check_operation()
        self.check_hunks()

    # ------------------------------------------------------------------ step 1

    def step1_skip(self) -> bool:
        b = self.b
        for hl in (b.new_file_mode, b.deleted_file_mode, b.old_mode, b.new_mode):
            if hl is not None and hl.value.strip() in NON_REGULAR_MODES:
                kind = "symbolic link" if hl.value.strip() == "120000" else "submodule"
                b.skipped_code = "W603"
                d = Diagnostic(code="W603", message="block skipped: %s (mode %s)" % (kind, hl.value.strip()),
                               block=b.ordinal, patch_line=hl.line_no)
                self.diags.add(d)
                b.warnings.append(d)
                return True
        if b.binary_line is not None:
            if b.deleted_file_mode is not None:
                # §1.1, §6.2, §6.4.4 step 1 (§12 item 30): a binary delete needs no file content and
                # proceeds as a delete; it is not skipped, so no W601
                return False
            b.skipped_code = "W601"
            d = Diagnostic(code="W601", message="binary file skipped", block=b.ordinal,
                           patch_line=b.binary_line.line_no)
            self.diags.add(d)
            b.warnings.append(d)
            return True
        # §6.4.1 (§12 item 30): submodule pointer update = `index` line and one hunk whose body
        # lines all begin with `-Subproject commit ` or `+Subproject commit `.
        if b.index_line is not None and len(b.hunks) == 1:
            els = b.hunks[0].elements
            if els and all(e.kind in (MINUS, PLUS) and e.content.startswith("Subproject commit ") for e in els):
                b.skipped_code = "W603"
                d = Diagnostic(code="W603", message="block skipped: submodule pointer update",
                               block=b.ordinal, patch_line=b.index_line.line_no)
                self.diags.add(d)
                b.warnings.append(d)
                return True
        return False

    def implied_operation(self) -> str:
        """§6.4.1 indicators, without validation (for skipped blocks): the first indicator in header
        order decides; no indicator → edit."""
        b = self.b
        indicators: List[Tuple[int, str]] = []
        if b.new_file_mode is not None:
            indicators.append((b.new_file_mode.line_no, "create"))
        if b.source == DEV_NULL and b.minus:
            indicators.append((b.minus[0].line_no, "create"))
        if b.deleted_file_mode is not None:
            indicators.append((b.deleted_file_mode.line_no, "delete"))
        if b.target == DEV_NULL and b.plus:
            indicators.append((b.plus[0].line_no, "delete"))
        if b.rename_from or b.rename_to:
            indicators.append(((b.rename_from or b.rename_to)[0].line_no, "rename"))
        if b.copy_from or b.copy_to:
            indicators.append(((b.copy_from or b.copy_to)[0].line_no, "copy"))
        if not indicators:
            return "edit"
        return min(indicators)[1]

    # ------------------------------------------------------------------ paths (§6.3)

    def process(self, raw: str, kind: str, hl: HeaderLine, report: bool) -> Optional[str]:
        try:
            return process_path(raw, kind, self.opts.strip)
        except PathError as e:
            if report and (e.code, raw) not in self.reported:
                self.reported.add((e.code, raw))
                self.err(e.code, e.message, hl)
            return None

    def extract_paths(self, report: bool) -> bool:
        """§6.3.1: determine source and target once. Returns False when a path could not be processed."""
        b = self.b
        ok = True
        self.dg_src = self.dg_dst = None
        self.minus_path = self.plus_path = None
        self.from_path = self.to_path = None
        self.dg_line = b.diff_git
        # diff --git <src> <dst>
        if b.diff_git is not None:
            try:
                dg = split_diff_git(b.diff_git.value, self.opts.strip)
                for raw, which in ((dg.src_raw, "src"), (dg.dst_raw, "dst")):
                    p = self.process(raw, "diff-git", b.diff_git, report)
                    if p is None:
                        ok = False
                    if which == "src":
                        self.dg_src = p
                    else:
                        self.dg_dst = p
            except PathError as e:
                if report:
                    self.err(e.code, e.message, b.diff_git)
                ok = False
                self.dg_line = None
        # --- / +++
        for lst, attr in ((b.minus, "minus_path"), (b.plus, "plus_path")):
            if not lst:
                continue
            hl = lst[0]
            try:
                raw = split_header_path(hl.value)
            except PathError as e:
                if report:
                    self.err(e.code, e.message, hl)
                ok = False
                continue
            p = self.process(raw, "header", hl, report)
            if p is None:
                ok = False
            setattr(self, attr, p)
        # rename/copy from/to (never prefix-stripped)
        op_from = b.rename_from or b.copy_from
        op_to = b.rename_to or b.copy_to
        if op_from:
            self.from_path = self.process(op_from[0].value, "operation", op_from[0], report)
            ok = ok and self.from_path is not None
        if op_to:
            self.to_path = self.process(op_to[0].value, "operation", op_to[0], report)
            ok = ok and self.to_path is not None
        # §6.3.1 extraction priority
        src = dst = None
        if self.dg_line is not None and self.dg_src is not None and self.dg_dst is not None:
            src, dst = self.dg_src, self.dg_dst
        elif b.minus or b.plus:
            src, dst = self.minus_path, self.plus_path
        elif op_from or op_to:
            src, dst = self.from_path, self.to_path
        elif report and b.diff_git is None:
            self.block_start_err("E210", "block has no path source (no `diff --git`, no `---`/`+++`, "
                                         "no `rename`/`copy` pair)")
            ok = False
        # rule 0: /dev/null on the `---`/`+++` side wins
        if self.minus_path == DEV_NULL:
            src = DEV_NULL
        if self.plus_path == DEV_NULL:
            dst = DEV_NULL
        b.source, b.target = src, dst
        return ok

    # ------------------------------------------------------------------ §6.3.2 consistency

    def check_path_consistency(self) -> None:
        b = self.b
        # 1. unpaired / duplicate path headers: reported by the state machine (E200)
        if any(d.code == "E200" for d in b.errors):
            return
        # 2. diff --git vs ---/+++
        if self.dg_line is not None and (b.minus or b.plus):
            if self.minus_path is not None and self.minus_path != DEV_NULL and self.minus_path != self.dg_src:
                self.err("E202", "`diff --git` source %r differs from the `---` path %r"
                         % (self.dg_src, self.minus_path), b.minus[0])
                return
            if self.plus_path is not None and self.plus_path != DEV_NULL and self.plus_path != self.dg_dst:
                self.err("E202", "`diff --git` target %r differs from the `+++` path %r"
                         % (self.dg_dst, self.plus_path), b.plus[0])
                return
        op_from = b.rename_from or b.copy_from
        op_to = b.rename_to or b.copy_to
        word = "rename" if (b.rename_from or b.rename_to) else "copy"
        # 3. operation header vs ---/+++
        if (op_from or op_to) and (b.minus or b.plus):
            if op_from and self.minus_path not in (None, DEV_NULL) and self.from_path != self.minus_path:
                self.err("E209", "`%s from %s` differs from the `---` path %r"
                         % (word, self.from_path, self.minus_path), _later(op_from[0], b.minus[0]))
                return
            if op_to and self.plus_path not in (None, DEV_NULL) and self.to_path != self.plus_path:
                self.err("E209", "`%s to %s` differs from the `+++` path %r"
                         % (word, self.to_path, self.plus_path), _later(op_to[0], b.plus[0]))
                return
        # 4. operation header vs diff --git (when ---/+++ are absent)
        if (op_from or op_to) and not (b.minus or b.plus) and self.dg_line is not None:
            if op_from and self.dg_src not in (None, DEV_NULL) and self.from_path != self.dg_src:
                self.err("E209", "`%s from %s` differs from the `diff --git` source %r"
                         % (word, self.from_path, self.dg_src), _later(op_from[0], self.dg_line))
                return
            if op_to and self.dg_dst not in (None, DEV_NULL) and self.to_path != self.dg_dst:
                self.err("E209", "`%s to %s` differs from the `diff --git` target %r"
                         % (word, self.to_path, self.dg_dst), _later(op_to[0], self.dg_line))
                return
        # 5. no implicit rename
        if not (op_from or op_to) and b.source not in (None, DEV_NULL) and b.target not in (None, DEV_NULL):
            if b.source != b.target and not self.opts.flag("auto-rename"):
                line = b.plus[0] if b.plus else self.dg_line
                hint = ("add `rename from %s` / `rename to %s` lines for a rename, or fix the typo"
                        % (b.source, b.target))
                if b.started_by_pair_after_body:
                    hint += ("; this header is a `---`/`+++` pair that ended the previous hunk body: a hunk "
                             "header may be missing in this block, or the pair may be a `-- `/`++ ` comment "
                             "edit (§7.2)")
                self.err("E608", "`---` and `+++` paths differ without `rename from`/`rename to`: %r vs %r"
                         % (b.source, b.target), line, hint=hint)

    # ------------------------------------------------------------------ §5.5 block options

    def check_block_options(self) -> None:
        b = self.b
        for ol in b.option_lines:
            if ol.name in BLOCK_FORBIDDEN:
                self.err("E309", "option %r is document-wide and not allowed at block level" % ol.name,
                         line_no=ol.line_no, line_text=ol.text)
            elif ol.name not in BLOCK_ALLOWED:
                self.err("E301", "unknown block-level option %r" % ol.name, line_no=ol.line_no, line_text=ol.text)
        mo = b.match_options
        block_lines: Dict[str, OptionLine] = {}
        for ol in b.option_lines:
            block_lines[ol.name] = ol
        # E305: apply-all-matches with first-match, effective per block. A first-match implied by
        # the 1.0 compatibility profile is not an option line and does not conflict (§5, §12 item 10:
        # "implied options never raise a conflict error such as E305").
        implied_only = self.opts.implied_first_match and "first-match" not in {ol.name for ol in b.option_lines}
        if mo.apply_all_matches and mo.first_match and not implied_only:
            involved = [block_lines.get("apply-all-matches"), block_lines.get("first-match")]
            if any(x is not None for x in involved):
                cands = [x for x in involved if x is not None]
                for name in ("apply-all-matches", "first-match"):
                    if name not in block_lines and name in self.opts.lines:
                        cands.append(self.opts.lines[name])
                later = max(cands, key=lambda x: x.line_no)
                self.err("E305", "`apply-all-matches` and `first-match` are mutually exclusive (effective in "
                                 "this block)", line_no=later.line_no, line_text=later.text)
        # E307: lenient with a global strict
        if mo.lenient and self.opts.flag("strict") and "lenient" in block_lines:
            ol = block_lines["lenient"]
            self.err("E307", "`option lenient` cannot be combined with --strict", line_no=ol.line_no,
                     line_text=ol.text)

    # ------------------------------------------------------------------ §6.4 operation

    def check_operation(self) -> None:
        b = self.b
        indicators: List[Tuple[str, int, HeaderLine]] = []
        if b.new_file_mode is not None:
            indicators.append(("create", b.new_file_mode.line_no, b.new_file_mode))
        if b.source == DEV_NULL and b.minus:
            indicators.append(("create", b.minus[0].line_no, b.minus[0]))
        if b.deleted_file_mode is not None:
            indicators.append(("delete", b.deleted_file_mode.line_no, b.deleted_file_mode))
        if b.target == DEV_NULL and b.plus:
            indicators.append(("delete", b.plus[0].line_no, b.plus[0]))
        for lst in (b.rename_from, b.rename_to):
            if lst:
                indicators.append(("rename", lst[0].line_no, lst[0]))
        for lst in (b.copy_from, b.copy_to):
            if lst:
                indicators.append(("copy", lst[0].line_no, lst[0]))
        ops = []
        for op, _, _ in sorted(indicators, key=lambda x: x[1]):
            if op not in ops:
                ops.append(op)
        if len(ops) > 1:
            # §6.4.2 mutual exclusion → E604, at the first line that introduces a second operation
            first = ops[0]
            offending = min((hl for op, _, hl in indicators if op != first), key=lambda hl: hl.line_no)
            self.err("E604", "operation indicators imply more than one operation: %s" % ", ".join(ops), offending)
        # §6.4.2 incomplete operations; §10 E605 (§12 item 25) also covers a duplicate `rename from`
        # or `rename to`. E606 likewise covers duplicate `copy` lines (§12 item 25).
        if bool(b.rename_from) != bool(b.rename_to) or len(b.rename_from) > 1 or len(b.rename_to) > 1:
            dup = b.rename_from[1:] + b.rename_to[1:]
            hl = min(dup, key=lambda x: x.line_no) if dup else (b.rename_from or b.rename_to)[-1]
            self.err("E605", "`rename from` and `rename to` must appear exactly once each", hl)
        if bool(b.copy_from) != bool(b.copy_to) or len(b.copy_from) > 1 or len(b.copy_to) > 1:
            dup = b.copy_from[1:] + b.copy_to[1:]
            hl = min(dup, key=lambda x: x.line_no) if dup else (b.copy_from or b.copy_to)[-1]
            self.err("E606", "`copy from` and `copy to` must appear exactly once each", hl)
        if ops:
            b.operation = ops[0]
        elif (self.opts.flag("auto-rename") and b.source not in (None, DEV_NULL)
              and b.target not in (None, DEV_NULL) and b.source != b.target):
            b.operation = "rename"     # §5.2 --auto-rename (v1.0 behavior)
        else:
            b.operation = "edit"

    # ------------------------------------------------------------------ §7, §6.4.5 hunks

    def check_hunks(self) -> None:
        b = self.b
        op = b.operation
        if b.match_options.apply_all_matches and len(b.hunks) > 1:
            self.block_start_err("E304", "--apply-all-matches is allowed only for blocks with exactly one hunk; "
                                         "this block has %d" % len(b.hunks))
        if op == "edit" and not b.hunks and b.old_mode is None and b.new_mode is None and not b.e404_reported:
            # §6.4.1 edit block without hunks and without mode lines
            hint = None
            if b.started_by_pair_after_body:
                hint = ("this block's header is a `---`/`+++` pair that ended the previous hunk body: a hunk "
                        "header may be missing, or the pair may be a `-- `/`++ ` comment edit (§7.2)")
            self.block_start_err("E404", "edit block without hunks (missing `@@`?)", hint=hint)
        if op == "create":
            for h in b.hunks[1:]:
                self.err("E415", "a create block contains at most one hunk", hunk=h,
                         line_no=h.header_line_no, line_text=h.header_text)
            for h in b.hunks[:1]:
                bad = next((e for e in h.elements if e.kind != PLUS), None)
                if bad is not None:
                    self.err("E415", "a create hunk consists of `+` lines only", hunk=h,
                             line_no=bad.line_no, line_text=bad.raw)
                elif not h.elements:
                    self.err("E416", "empty hunk body", hunk=h, line_no=h.header_line_no, line_text=h.header_text)
            return
        if op == "delete":
            for h in b.hunks:
                bad = next((e for e in h.elements if e.kind == PLUS), None)
                if bad is not None:
                    self.err("E415", "a hunk of a delete block must not contain `+` lines", hunk=h,
                             line_no=bad.line_no, line_text=bad.raw)
                    continue
                self.check_general_hunk(h, allow_e412=False)
            return
        for h in b.hunks:
            self.check_general_hunk(h, allow_e412=True)

    def check_general_hunk(self, h: Hunk, allow_e412: bool) -> None:
        b = self.b
        kind = h.header.kind
        if not h.elements:
            self.err("E416", "empty hunk body", hunk=h, line_no=h.header_line_no, line_text=h.header_text)
            return
        # §7.1 position of BOF/EOF
        if kind == "bof" and h is not b.hunks[0]:
            self.err("E417", "`@@ BOF` must be the first hunk of its block", hunk=h,
                     line_no=h.header_line_no, line_text=h.header_text)
        if kind == "eof" and h is not b.hunks[-1]:
            self.err("E417", "`@@ EOF` must be the last hunk of its block", hunk=h,
                     line_no=h.header_line_no, line_text=h.header_text)
        if kind in ("bof", "eof"):
            bad = next((e for e in h.elements if e.kind != PLUS), None)
            if bad is not None:
                self.err("E411", "only `+` lines are allowed after `@@ %s`" % kind.upper(), hunk=h,
                         line_no=bad.line_no, line_text=bad.raw,
                         hint="an empty line to insert is `+` alone; a bare blank line is empty context")
            return
        anchors = h.anchors
        if allow_e412 and h.has_plus and not anchors:
            hint = "use `@@ BOF` or `@@ EOF`, or add a context line"
            if kind == "scope" and (h.header.scope or "").lower() in ("bof", "eof"):
                hint = "did you mean `@@ %s` (uppercase)?" % h.header.scope.upper()
            self.err("E412", "hunk has `+` lines but no anchor element: it has no position in the file", hunk=h,
                     line_no=h.header_line_no, line_text=h.header_text, hint=hint)
            return
        self.check_markers(h)

    def check_markers(self, h: Hunk) -> None:
        """§7.3 prohibited forms, in order of precedence: E511, E510, E512."""
        anchors = h.anchors
        for k, e in enumerate(anchors):
            if e.kind != MARKER:
                continue
            prev = anchors[k - 1] if k > 0 else None
            nxt = anchors[k + 1] if k + 1 < len(anchors) else None
            if prev is None or nxt is None:
                self.err("E511", "`...` at the %s of the hunk (no anchor element %s it)"
                         % (("beginning", "before") if prev is None else ("end", "after")),
                         hunk=h, line_no=e.line_no, line_text=e.raw)
            elif prev.kind == MARKER:
                self.err("E510", "two `...` markers without an anchor element between them", hunk=h,
                         line_no=e.line_no, line_text=e.raw)
            elif nxt.kind == MARKER:
                continue    # reported as E510 at the next marker
            elif prev.kind != MINUS or nxt.kind != MINUS:
                self.err("E512", "the nearest anchor element on each side of `...` must be a `-` line", hunk=h,
                         line_no=e.line_no, line_text=e.raw)


def _later(a: HeaderLine, b: HeaderLine) -> HeaderLine:
    return a if a.line_no > b.line_no else b


def validate_blocks(blocks: List[Block], opts: GlobalOptions, diags: DiagnosticList) -> None:
    for b in blocks:
        BlockValidator(b, opts, diags).run()
