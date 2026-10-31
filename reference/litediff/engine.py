"""The three phases of §8.1 and the per-hunk search of §8.2.

1. Parse phase: state machine (§4.1) + block validation (§6.4.4 steps 1–4). All parse errors
   are collected; a document with any parse error is not applied.
2. Match phase: for each block in document order, against the in-memory file-system state:
   path type (E103), file-system state (E6xx), matching and application in memory. Stop at the
   first failing block — except in check mode, which continues past failing blocks and hunks
   (§12 item 33, `checkedWithSkips`).
3. Write phase: only if every block succeeded and --check is not set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import compare as cmpmod
from .applier import apply_insertion, apply_match
from .diagnose import e410_content, neighbor_lines
from .diagnostics import Diagnostic, DiagnosticList, visible
from .matcher import (LEVEL_EXACT, LEVEL_INDENT, LEVEL_LENIENT, Comparator, Match, Pattern, PatternMatcher,
                      applied_pattern, build_pattern, compute_sigma, find_candidates, w511_findings)
from .model import BLANK, CONTEXT, MINUS, PLUS, Block, Document, Hunk
from .options import GlobalOptions, MatchOptions
from .parser import HostOptions, Parser, check_patch_encoding, split_patch_lines
from .paths import DEV_NULL
from .textfile import TextFile, created_file
from .validate import validate_blocks
from .workspace import Workspace


@dataclass
class HunkOutcome:
    status: str = "not-attempted"
    applied_range: Optional[Tuple[int, int]] = None      # 1-based first line, line count
    all_ranges: List[Tuple[int, int]] = field(default_factory=list)
    level: Optional[str] = None
    scope_line: Optional[int] = None                     # 1-based


@dataclass
class BlockOutcome:
    status: str = "not-attempted"
    hunks: List[HunkOutcome] = field(default_factory=list)


class HunkFailed(Exception):
    """Raised inside the hunk loop when the current hunk fails (error or escalated warning)."""


@dataclass
class BlockState:
    """Search cursor and line delta of §3.1 / §8.2 step 2 (reset between blocks)."""

    cursor: int = 0
    delta: int = 0
    prev_range: Optional[Tuple[int, int]] = None          # 0-based (start, length) of the previous hunk
    # §1.3 "Final terminator" (§12 item 23): decision of the last hunk that reached the end of file
    # (True: new-side sentinel → unterminated), None while no hunk reached it
    eof_unterminated: Optional[bool] = None


class Engine:
    def __init__(self, patch: bytes, workdir: str, host: Optional[HostOptions] = None) -> None:
        self.host = host or HostOptions()
        self.encoding_problem = check_patch_encoding(patch)     # E310 (§12 item 9)
        self.lines = split_patch_lines(patch)
        self.workdir = workdir
        self.doc: Optional[Document] = None
        self.opts: Optional[GlobalOptions] = None
        self.diags: Optional[DiagnosticList] = None
        self.outcomes: Dict[int, BlockOutcome] = {}
        self.written: List[str] = []
        self.status = "failed"
        self.write_error: Optional[str] = None
        self.check = False
        self.checked_with_skips = False                   # §8.6 check mode (§12 item 33)

    # ------------------------------------------------------------------ phases

    def run(self) -> "Engine":
        parser = Parser(self.lines, self.host, self.encoding_problem)
        self.doc = parser.parse()
        self.opts = parser.opts
        self.diags = parser.diags
        self.check = self.opts.flag("check")
        if not self.doc.blocks:
            # §10 W302 (§12 item 9): no diff block; status `applied` (or `checked`), nothing written
            self.diags.add(Diagnostic(code="W302", message="the document contains no diff block: nothing to apply"))
        validate_blocks(self.doc.blocks, self.opts, self.diags)
        for b in self.doc.blocks:
            self.outcomes[b.ordinal] = BlockOutcome(hunks=[HunkOutcome() for _ in b.hunks])
        if self.diags.has_errors():
            self.parse_failed()
            return self
        self.ws = Workspace(self.workdir)
        check = self.check
        failed_any = False
        for b in self.doc.blocks:
            if not self.run_block(b):
                if not check:
                    self.after_failure(b)
                    return self
                # §8.6 check mode (§12 item 33): continue with the remaining blocks against the
                # in-memory state as if the failed block had been skipped (run_block changes the
                # workspace only when the block succeeds)
                self.outcomes[b.ordinal].status = "failed"
                failed_any = True
        for b in self.doc.blocks:
            out = self.outcomes[b.ordinal]
            if out.status not in ("skipped", "failed"):
                out.status = "checked" if check else "applied"
            for ho in out.hunks:
                if ho.status == "matched":
                    ho.status = "checked" if check else out.status
        if check:
            self.status = "failed" if failed_any else "checked"
            self.checked_with_skips = failed_any
            return self
        self.written, self.write_error = self.ws.commit()
        self.status = "failed" if self.write_error else "applied"
        return self

    def parse_failed(self) -> None:
        """§8.6: blocks with parse errors `failed`, all other blocks `not-attempted`; in a failed
        block, hunks that carry an error `failed`, the others `not-attempted`."""
        for b in self.doc.blocks:
            out = self.outcomes[b.ordinal]
            if b.has_parse_error:
                out.status = "failed"
                for h, ho in zip(b.hunks, out.hunks):
                    ho.status = "failed" if any(d.is_error for d in h.errors) else "not-attempted"
            else:
                out.status = "not-attempted"
        self.status = "failed"

    def after_failure(self, failed: Block) -> None:
        """§8.6: blocks before the failing one `matched`, after it `not-attempted`."""
        for b in self.doc.blocks:
            out = self.outcomes[b.ordinal]
            if b.ordinal < failed.ordinal:
                if out.status != "skipped":
                    out.status = "matched"
            elif b.ordinal == failed.ordinal:
                out.status = "failed"
            else:
                out.status = "not-attempted"
        self.status = "failed"

    # ------------------------------------------------------------------ diagnostics

    def diag(self, code: str, message: str, b: Block, h: Optional[Hunk] = None, hint: Optional[str] = None,
             escalate: bool = True, **extra: Any) -> Diagnostic:
        d = Diagnostic(code=code, message=message, block=b.ordinal, hunk=h.ordinal if h else None, hint=hint,
                       extra={k: v for k, v in extra.items() if v is not None})
        return self.diags.add(d, escalate=escalate)

    def warn(self, code: str, message: str, b: Block, h: Optional[Hunk] = None, escalate: bool = True,
             **extra: Any) -> None:
        """A warning; under --strict an escalated warning fails the hunk (§5.2)."""
        d = self.diag(code, message, b, h, escalate=escalate, **extra)
        if d.escalated:
            raise HunkFailed()

    def final_terminator(self, b: Block, h: Hunk, st: BlockState, reaches_eof: bool,
                         last_terminated: Optional[bool]) -> None:
        """§1.3 "Final terminator" (§12 item 23) for one applied hunk.

        A hunk reaches the end of file when its anchor block includes the file's last line or it is
        an `@@ EOF` hunk; the new side of the last such hunk decides. An old-side sentinel that
        contradicts the file (the last line, as matched, is terminated), a misplaced sentinel, and a
        sentinel in a hunk that does not reach the end of file are W419 and have no effect."""
        if not reaches_eof:
            if h.sentinel_lines:
                self.diag("W419", "`\\ No newline at end of file` in a hunk that does not reach the end of file: "
                                  "ignored (patch line %s)" % ", ".join(map(str, h.sentinel_lines)), b, h,
                          **{"x-patchLines": list(h.sentinel_lines)})
            return
        if h.sentinel_misplaced:
            self.diag("W419", "`\\ No newline at end of file` not after the last line of the old or the new side: "
                              "ignored (patch line %s)" % ", ".join(map(str, h.sentinel_misplaced)), b, h,
                      **{"x-patchLines": list(h.sentinel_misplaced)})
        if h.sentinel_old_end and last_terminated:
            self.diag("W419", "old-side `\\ No newline at end of file` says the file's last line has no final "
                              "newline, but it has one: ignored", b, h)
        st.eof_unterminated = h.sentinel_new_end

    # ------------------------------------------------------------------ blocks (§6.4.4 steps 5–7)

    def run_block(self, b: Block) -> bool:
        out = self.outcomes[b.ordinal]
        if b.skipped_code is not None:
            out.status = "skipped"
            for ho in out.hunks:
                ho.status = "skipped"
            return True
        ws = self.ws
        op = b.operation
        # step 5: path type
        for path in (b.source, b.target):
            if path not in (None, DEV_NULL) and ws.is_symlink(path):
                self.diag("E103", "path %r leads to a symbolic link" % path, b)
                return False
        # step 6: file-system state
        if op == "create":
            if ws.exists(b.target):
                self.diag("E600", "cannot create %r: it already exists" % b.target, b)
                return False
        elif op == "delete":
            if not ws.is_file(b.source):
                self.diag("E601", "cannot delete %r: not found or not a regular file" % b.source, b)
                return False
        elif op in ("rename", "copy"):
            if not ws.is_file(b.source):
                self.diag("E603", "%s source %r does not exist" % (op, b.source), b)
                return False
            if ws.exists(b.target):
                self.diag("E602", "%s target %r already exists" % (op, b.target), b)
                return False
        else:
            if not ws.is_file(b.source):
                self.diag("E611", "file %r not found for edit" % b.source, b)
                return False
        # step 7: content
        if op == "create":
            return self.run_create(b, out)
        if op == "delete":
            self.check_w602(b)
            ws.delete(b.source)
            for ho in out.hunks:
                ho.status = "skipped"            # hunks of a delete block are not applied (§6.4.5)
            out.status = "matched"
            return True
        tf = TextFile.parse(ws.read(b.source), self.opts.eol_bytes)
        if not b.hunks and op == "edit":
            # §6.4.1 mode-change-only block: nothing is changed, W412 is mandatory
            d = self.diag("W412", "mode change only: no content change (no-op)", b)
            if d.escalated:
                return False
        state = BlockState()
        block_failed = False
        for h, ho in zip(b.hunks, out.hunks):
            try:
                self.run_hunk(b, h, ho, tf, state)
            except HunkFailed:
                ho.status = "failed"
                if not self.check:
                    return False
                # §8.6 check mode: every hunk receives a status; the next hunk is matched as if the
                # failed one had been skipped (cursor unchanged). The block's result is discarded.
                block_failed = True
        if block_failed:
            return False
        tf.finalize(state.eof_unterminated)
        data = tf.to_bytes()
        if op == "edit":
            ws.write(b.source, data)
        elif op == "rename":
            ws.write(b.target, data)
            ws.delete(b.source)
        else:   # copy
            ws.write(b.target, data)
        out.status = "matched"
        return True

    def run_create(self, b: Block, out: BlockOutcome) -> bool:
        contents: List[bytes] = []
        unterminated = False
        if b.hunks:
            h = b.hunks[0]
            contents = [e.content.encode("utf-8") for e in h.elements if e.kind == PLUS]
            unterminated = h.sentinel_after_last_plus          # §6.4.5: new-side sentinel after the last `+`
            if h.sentinel_misplaced:
                self.diag("W419", "`\\ No newline at end of file` not after the last `+` line of the create hunk: "
                                  "ignored (patch line %s)" % ", ".join(map(str, h.sentinel_misplaced)), b, h,
                          **{"x-patchLines": list(h.sentinel_misplaced)})
            out.hunks[0].status = "matched"
            out.hunks[0].applied_range = (1, len(contents))
            out.hunks[0].level = LEVEL_EXACT
        self.ws.write(b.target, created_file(contents, self.opts.eol_bytes, unterminated))
        out.status = "matched"
        return True

    def check_w602(self, b: Block) -> None:
        """§6.4.5 MAY: compare the `-` lines of a delete block's hunks with the file (W602)."""
        if not b.hunks:
            return
        tf = TextFile.parse(self.ws.read(b.source), self.opts.eol_bytes)
        for h in b.hunks:
            pattern = build_pattern(h, False)
            if pattern.is_empty:
                continue
            pm = PatternMatcher(pattern, Comparator(tf.lines, MatchOptions(), LEVEL_EXACT), False)
            if not pm.matches_from(0):
                self.diag("W602", "hunk %d of the delete block does not match the file being deleted "
                                  "(the file is deleted anyway)" % h.ordinal, b)
                return

    # ------------------------------------------------------------------ hunks (§8.2)

    def run_hunk(self, b: Block, h: Hunk, ho: HunkOutcome, tf: TextFile, st: BlockState) -> None:
        mo = b.match_options
        kind = h.header.kind
        n = len(tf.lines)
        # step 3: special cases
        if kind == "bof":
            self.final_terminator(b, h, st, False, None)
            start, k = apply_insertion(h, tf, 0)
            self.record(ho, st, start, k, 0, LEVEL_EXACT)
            return
        if kind == "eof":
            # an `@@ EOF` hunk always reaches the end of file (§1.3)
            self.final_terminator(b, h, st, True, tf.lines[-1].term is not None if tf.lines else None)
            start, k = apply_insertion(h, tf, n)
            self.record(ho, st, start, k, 0, LEVEL_EXACT)
            return
        # step 2a: search start
        S = st.cursor
        scope_line: Optional[int] = None
        if kind == "scope":
            S = self.scope_start(b, h, tf, st, mo)
            scope_line = S
            ho.scope_line = S + 1
        pattern = build_pattern(h, mo.ignore_blank_lines)
        if pattern.is_empty:
            self.diag("E410", "the anchor consists only of blank context lines, which --ignore-blank-lines removes "
                              "from the anchor pattern: the hunk has no position", b, h,
                      searchStart=S + 1, cursor=st.cursor + 1)
            raise HunkFailed()
        if mo.apply_all_matches:
            self.run_apply_all(b, h, ho, tf, st, pattern, S, scope_line)
            return
        outcome = find_candidates(pattern, tf.lines, mo, h, S)
        if not outcome.candidates:
            self.no_candidate(b, h, ho, tf, st, pattern, S, scope_line, outcome.refused_plus, allow_e413=True)
            return
        cands = outcome.candidates
        chosen = cands[0]
        if len(cands) > 1:
            # step 6: ambiguity, in this order of precedence
            if self.qualifying(h):
                expected = h.header.old_start - 1 + st.delta
                chosen = min(cands, key=lambda m: (abs(m.start - expected), m.start))
                exact = chosen.start == expected
                # §5.2 (§12 item 21): W410 is not escalated under --strict when the chosen candidate
                # starts exactly at `expected`
                self.warn("W410", "ambiguous anchor (%d candidates) resolved by the unified header: old start %d "
                                  "with line delta %+d → line %d (%s)"
                          % (len(cands), h.header.old_start, st.delta, chosen.start + 1,
                             "exact hit" if exact else "closest candidate, not an exact hit"), b, h,
                          escalate=not exact, searchStart=S + 1, cursor=st.cursor + 1,
                          candidates=self.candidate_list(cands, tf, chosen), **{"x-exactHit": exact})
            elif mo.first_match:
                chosen = cands[0]
            else:
                self.diag("E414", "ambiguous anchor: the pattern matches at %d places from line %d (lines %s); "
                                  "add distinctive context or a `@@ <scope>` header"
                          % (len(cands), S + 1, ", ".join(str(m.start + 1) for m in cands)), b, h,
                          searchStart=S + 1, cursor=st.cursor + 1,
                          candidates=self.candidate_list(cands, tf, None))
                raise HunkFailed()
        # step 5 "Already present" (§12 item 20): a pure insertion whose result is already there
        if self.present_or_skip(b, h, ho, tf, st, chosen):
            return
        if len(cands) == 1:
            # step 8: suspicious order (W413) — exactly one candidate, and a match before the cursor
            earlier = self.level_matches(outcome.matcher, pattern, tf, h, 0, st.cursor)
            if earlier:
                cl = self.candidate_list(earlier + [chosen], tf, chosen)
                self.warn("W413", "anchor also matches before the cursor (line %s); applied at line %d after the "
                                  "cursor — check the hunk order and the applied range"
                          % (", ".join(str(m.start + 1) for m in earlier), chosen.start + 1), b, h,
                          searchStart=S + 1, cursor=st.cursor + 1, candidates=cl)
        self.apply_one(b, h, ho, tf, st, pattern, chosen, outcome.matcher)

    def already_present(self, h: Hunk, tf: TextFile, m: Match, mo: MatchOptions) -> Optional[Match]:
        """§8.2 step 5 "Already present": for a hunk with `+` lines and no `-` line, does its applied
        pattern also match at the candidate position?

        "At the candidate position" is read with the applied pattern aligned on the anchor: when k
        `+` lines precede the first anchor element, the applied pattern is tried k lines before the
        candidate (where a previous application put them). The comparison is that of the level the
        candidate was found at (spec finding, README)."""
        if not h.has_plus or h.has_minus:
            return None
        ibl = mo.ignore_blank_lines
        ap = applied_pattern(h, ibl)
        if ap.is_empty:
            return None
        k = 0
        for e in h.elements:
            if e.is_anchor:
                break
            if e.kind == PLUS and not (ibl and e.content.strip(" \t") == ""):
                k += 1
        q = m.start - k
        if q < 0:
            return None
        res = PatternMatcher(ap, Comparator(tf.lines, mo, m.level), ibl).match_at(q)
        return res if isinstance(res, Match) else None

    def present_or_skip(self, b: Block, h: Hunk, ho: HunkOutcome, tf: TextFile, st: BlockState, m: Match) -> bool:
        """W417, or W414 under --skip-applied (§5.2, §8.2 step 5). Returns True when the hunk was skipped."""
        mo = b.match_options
        present = self.already_present(h, tf, m, mo)
        if present is None:
            return False
        if mo.skip_applied:
            self.diag("W414", "insertion already present at line %d (the anchor matches at line %d): hunk skipped "
                              "(--skip-applied)" % (present.start + 1, m.start + 1), b, h,
                      **{"x-line": present.start + 1})
            st.cursor = present.end
            st.prev_range = (present.start, present.end - present.start)
            if ho.applied_range is None:
                ho.status = "skipped"
            return True
        self.warn("W417", "insertion already present at the match position (line %d): applying the hunk duplicates "
                          "it; was the patch applied before?" % (present.start + 1), b, h,
                  **{"x-line": present.start + 1})
        return False

    def scope_start(self, b: Block, h: Hunk, tf: TextFile, st: BlockState, mo: MatchOptions) -> int:
        """§8.2 step 2a: S = the first line ≥ cursor containing the scope text; E418 / W418."""
        text = h.header.scope or ""
        scope = text.encode("utf-8")
        hits = [p for p in range(st.cursor, len(tf.lines)) if cmpmod.contains_scope(tf.lines[p].content, scope, mo)]
        if not hits:
            before = [p for p in range(0, min(st.cursor, len(tf.lines)))
                      if cmpmod.contains_scope(tf.lines[p].content, scope, mo)]
            msg = "scope text %r not found from the cursor (line %d) to the end of file" % (text, st.cursor + 1)
            if before:
                msg += "; it occurs before the cursor at line %s (hunk order?)" % ", ".join(str(p + 1) for p in before)
            else:
                msg += "; it does not occur before the cursor either"
            hint = None
            if text.lower() in ("bof", "eof"):
                hint = "did you mean `@@ %s` (uppercase)?" % text.upper()
            self.diag("E418", msg, b, h, hint=hint, cursor=st.cursor + 1,
                      **{"x-scopeText": text, "x-occursBeforeCursor": [p + 1 for p in before]})
            raise HunkFailed()
        S = hits[0]
        if len(hits) > 1:
            self.warn("W418", "scope text %r occurs %d times from the cursor (lines %s); the first (line %d) was used"
                      % (text, len(hits), ", ".join(str(p + 1) for p in hits), S + 1), b, h,
                      cursor=st.cursor + 1,
                      candidates=[dict({"line": p + 1}, **({"chosen": True} if p == S else {})) for p in hits])
        return S

    def qualifying(self, h: Hunk) -> bool:
        """§8.2 step 6.2: a unified header qualifies when the body has no `...` and its counts are
        consistent with the body as written for one t' with 0 ≤ t' ≤ t (omitted count = 1)."""
        hh = h.header
        if hh.kind != "unified" or h.has_marker:
            return False
        m = 1 if hh.old_count is None else hh.old_count
        n = 1 if hh.new_count is None else hh.new_count
        ctx = sum(1 for e in h.elements if e.kind in (CONTEXT, BLANK))
        minus = sum(1 for e in h.elements if e.kind == MINUS)
        plus = sum(1 for e in h.elements if e.kind == PLUS)
        t1 = m - ctx - minus
        t2 = n - ctx - plus
        return t1 == t2 and 0 <= t1 <= h.trailing_blanks

    def level_matches(self, pm: PatternMatcher, pattern: Pattern, tf: TextFile, h: Hunk, lo: int, hi: int) -> List[Match]:
        """Matches with start in [lo, hi) at the level of `pm` (σ-checked at level (b))."""
        raw = pm.matches_from(lo, hi)
        if pm.cmp.level != LEVEL_INDENT:
            return raw
        plus = [e for e in h.elements if e.kind == PLUS]
        return [m for m in raw if compute_sigma(m, pattern, tf.lines, plus).ok]

    def candidate_list(self, matches: List[Match], tf: TextFile, chosen: Optional[Match]) -> List[Dict[str, Any]]:
        out = []
        for m in matches:
            item: Dict[str, Any] = {"line": m.start + 1}
            if chosen is not None and m is chosen:
                item["chosen"] = True
            item.update(neighbor_lines(tf.lines, m.start, m.end))
            out.append(item)
        return out

    def apply_one(self, b: Block, h: Hunk, ho: HunkOutcome, tf: TextFile, st: BlockState, pattern: Pattern,
                  m: Match, pm: PatternMatcher) -> Tuple[int, int, int]:
        """Warnings that depend on the chosen match, then the §8.3 replacement."""
        # W511 (§7.3), in the coordinates of the file as matched
        for f in w511_findings(m, pm):
            self.warn("W511", "segment %d ends with a `-` line and would also match later (line %d) than its chosen "
                              "position (line %d): add a context line after the last `-` line or make it unique"
                      % (f.segment, f.later + 1, f.chosen + 1), b, h,
                      candidates=[{"line": f.chosen + 1, "chosen": True}, {"line": f.later + 1}],
                      **{"x-segment": f.segment})
        if m.level == LEVEL_INDENT:
            table = [{"from": k.decode("utf-8", "replace"), "to": v.decode("utf-8", "replace")}
                     for k, v in m.sigma.items()]
            self.warn("W415", "hunk applied with re-indentation at line %d: %s"
                      % (m.start + 1, ", ".join("%s → %s" % (visible(t["from"]) or "(none)", visible(t["to"]) or "(none)")
                                                for t in table)), b, h, reindent=table,
                      **{"x-line": m.start + 1})
        elif m.level == LEVEL_LENIENT:
            self.warn("W416", "hunk matched at line %d ignoring the amount of whitespace (--lenient); "
                              "`+` lines written as given" % (m.start + 1), b, h, **{"x-line": m.start + 1})
        if not h.has_plus and not h.has_minus:
            self.warn("W412", "hunk contains no `+` or `-` lines: no-op (forgotten prefixes?)", b, h)
        reaches_eof = m.end == len(tf.lines)
        self.final_terminator(b, h, st, reaches_eof, tf.lines[-1].term is not None if tf.lines else None)
        start, outlen, anchorlen = apply_match(h, pattern, m, tf)
        self.record(ho, st, start, outlen, anchorlen, m.level)
        return start, outlen, anchorlen

    def record(self, ho: HunkOutcome, st: BlockState, start: int, outlen: int, anchorlen: int, level: str) -> None:
        """Cursor and delta update of §8.2 step 2; the applied range of §8.6."""
        st.cursor = start + outlen
        st.delta += outlen - anchorlen
        st.prev_range = (start, outlen)
        if ho.applied_range is None:
            ho.applied_range = (start + 1, outlen)
            ho.level = level
        ho.all_ranges.append((start + 1, outlen))
        ho.status = "matched"

    def run_apply_all(self, b: Block, h: Hunk, ho: HunkOutcome, tf: TextFile, st: BlockState, pattern: Pattern,
                      S: int, scope_line: Optional[int]) -> None:
        """§8.4: apply to every non-overlapping occurrence, left to right; steps 6–8 do not apply."""
        mo = b.match_options
        outcome = find_candidates(pattern, tf.lines, mo, h, S)
        if not outcome.candidates:
            self.no_candidate(b, h, ho, tf, st, pattern, S, scope_line, outcome.refused_plus, allow_e413=False)
            return
        level = outcome.level
        m, pm = outcome.candidates[0], outcome.matcher
        while True:
            # W417 / W414 per occurrence (the text does not exclude --apply-all-matches from §8.2 step 5)
            if not self.present_or_skip(b, h, ho, tf, st, m):
                self.apply_one(b, h, ho, tf, st, pattern, m, pm)
            nxt = find_candidates(pattern, tf.lines, mo, h, st.cursor, levels=[level])
            if not nxt.candidates:
                break
            m, pm = nxt.candidates[0], nxt.matcher

    def no_candidate(self, b: Block, h: Hunk, ho: HunkOutcome, tf: TextFile, st: BlockState, pattern: Pattern,
                     S: int, scope_line: Optional[int], refused_plus, allow_e413: bool) -> None:
        """No level yields a candidate: W414 (--skip-applied), E413 (step 7) or E410 (step 5)."""
        mo = b.match_options
        ibl = mo.ignore_blank_lines
        # "Already applied": the applied pattern matches at level (a) exactly once from S
        already: Optional[Match] = None
        ap = applied_pattern(h, ibl)
        if not ap.is_empty:
            hits = PatternMatcher(ap, Comparator(tf.lines, mo, LEVEL_EXACT), ibl).matches_from(S)
            if len(hits) == 1:
                already = hits[0]
        if already is not None and mo.skip_applied:
            self.diag("W414", "hunk appears to be already applied at line %d and was skipped (--skip-applied)"
                      % (already.start + 1), b, h, **{"x-line": already.start + 1})
            ho.status = "skipped"
            st.cursor = already.end
            st.prev_range = (already.start, already.end - already.start)
            return
        # §12 item 20: the "already applied" test precedes the hunk-order search of step 7, so a
        # re-applied hunk is reported as E410 "already applied", not as E413
        if allow_e413 and already is None:
            # step 7: the pattern matches (at level (a)) before the search start
            pm_a = PatternMatcher(pattern, Comparator(tf.lines, mo, LEVEL_EXACT), ibl)
            earlier = pm_a.matches_from(0, S)
            if earlier:
                p = earlier[0].start
                if st.cursor <= p:
                    cls, text = "above-scope", "the anchor lies above the scope line (check the scope text)"
                elif st.prev_range is not None and st.prev_range[0] <= p < st.prev_range[0] + st.prev_range[1]:
                    cls, text = ("shared-context", "it lies inside the applied range of the previous hunk: the hunk "
                                 "repeats the previous hunk's trailing lines (merge the hunks or drop the shared lines)")
                else:
                    cls, text = "wrong-order", "it lies before the previous hunk: the hunks are in the wrong order"
                msg = ("no match from line %d (cursor line %d), but the anchor pattern matches before it at line %d: %s"
                       % (S + 1, st.cursor + 1, p + 1, text))
                msg += "; the hunk does not appear to be already applied"
                self.diag("E413", msg, b, h, classification=cls, searchStart=S + 1, cursor=st.cursor + 1,
                          candidates=[{"line": m.start + 1} for m in earlier])
                raise HunkFailed()
        content = e410_content(h, pattern, tf.lines, mo, S, st.cursor,
                               already.start if already is not None else None, refused_plus, scope_line)
        self.diag("E410", content["message"], b, h, hint=content["hint"], **content["extra"])
        raise HunkFailed()


def apply_document(patch: bytes, workdir: str, host: Optional[HostOptions] = None) -> Engine:
    return Engine(patch, workdir, host).run()
