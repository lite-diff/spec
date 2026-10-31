"""Anchor pattern matching (§7.3 segments, §8.2 steps 4–6, §5.1 --ignore-blank-lines, levels).

Vocabulary:
- pattern element: an anchor element of the hunk (context, blank, `-`), carried with its
  1-based index among *all* anchor elements of the hunk (markers included), so diagnostics can
  name it;
- segment: a maximal run of pattern elements between `...` markers (§7.3);
- candidate: a start position p ≥ S at which the whole pattern matches (§8.2 step 6).

A `Comparator` encapsulates one matching level: (a) exact under the active --ignore-* options,
(b) re-indentation (rests compared, indents collected into σ), (c) --ignore-space-change.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import compare as cmpmod
from .model import BLANK, CONTEXT, MARKER, MINUS, PLUS, BodyElement, Hunk
from .options import MatchOptions
from .textfile import FileLine

LEVEL_EXACT = "exact"
LEVEL_INDENT = "indent-shift"
LEVEL_LENIENT = "lenient"


# ---------------------------------------------------------------------------------------------
# pattern
# ---------------------------------------------------------------------------------------------

@dataclass
class PatEl:
    elem: BodyElement
    data: bytes             # UTF-8 bytes of the content after the prefix
    anchor_index: int       # 1-based among all anchor elements of the hunk (markers included)

    @property
    def is_minus(self) -> bool:
        return self.elem.kind == MINUS


@dataclass
class Pattern:
    segments: List[List[PatEl]]
    removed_blank_contexts: List[BodyElement] = field(default_factory=list)

    @property
    def elements(self) -> List[PatEl]:
        return [pe for seg in self.segments for pe in seg]

    @property
    def is_empty(self) -> bool:
        return not any(self.segments)


def build_pattern(hunk: Hunk, ibl: bool) -> Pattern:
    """§3.1 "Anchor pattern" split into §7.3 segments. Under --ignore-blank-lines blank context
    elements are removed from the pattern (§5.1)."""
    segments: List[List[PatEl]] = [[]]
    removed: List[BodyElement] = []
    index = 0
    for e in hunk.elements:
        if not e.is_anchor:
            continue
        index += 1
        if e.kind == MARKER:
            segments.append([])
            continue
        if ibl and e.kind in (BLANK, CONTEXT) and e.is_blank_context:
            removed.append(e)
            continue
        segments[-1].append(PatEl(e, e.content.encode("utf-8"), index))
    return Pattern(segments, removed)


def applied_pattern(hunk: Hunk, ibl: bool) -> Pattern:
    """§8.2 step 5 "Already applied": the output sequence of §8.3 — context, blank and `+` lines in
    body order (`-` lines and `...` omitted) — as one contiguous segment."""
    seg: List[PatEl] = []
    for k, e in enumerate(hunk.elements, 1):
        if e.kind in (CONTEXT, BLANK, PLUS):
            if ibl and (e.content.strip(" \t") == ""):
                continue
            pseudo = BodyElement(CONTEXT, e.content, e.line_no, e.raw)
            seg.append(PatEl(pseudo, e.content.encode("utf-8"), k))
    return Pattern([seg])


# ---------------------------------------------------------------------------------------------
# comparators (levels)
# ---------------------------------------------------------------------------------------------

class Comparator:
    """Compares pattern elements with file lines at one level (§8.2 step 5)."""

    def __init__(self, lines: List[FileLine], opts: MatchOptions, level: str = LEVEL_EXACT) -> None:
        self.lines = lines
        self.level = level
        # level (c) compares with --ignore-space-change semantics (§5.2 --lenient)
        self.opts = opts.with_space_change() if level == LEVEL_LENIENT else opts
        self._file_keys: Dict[int, bytes] = {}
        self._pattern_keys: Dict[int, bytes] = {}    # id(PatEl) → key (pattern objects outlive the comparator)
        self._blank: Dict[int, bool] = {}

    @property
    def n(self) -> int:
        return len(self.lines)

    def _project(self, data: bytes) -> bytes:
        if self.level == LEVEL_INDENT:
            return cmpmod.key(cmpmod.split_indent(cmpmod.strip_trailing(data))[1], self.opts)
        return cmpmod.key(data, self.opts)

    def file_key(self, i: int) -> bytes:
        k = self._file_keys.get(i)
        if k is None:
            k = self._project(self.lines[i].content)
            self._file_keys[i] = k
        return k

    def is_blank(self, i: int) -> bool:
        b = self._blank.get(i)
        if b is None:
            b = cmpmod.is_blank_bytes(self.lines[i].content)
            self._blank[i] = b
        return b

    def pattern_key(self, pe: PatEl) -> bytes:
        k = self._pattern_keys.get(id(pe))
        if k is None:
            k = self._project(pe.data)
            self._pattern_keys[id(pe)] = k
        return k

    def eq(self, pe: PatEl, i: int) -> bool:
        if i >= self.n:
            return False
        return self.pattern_key(pe) == self.file_key(i)


# ---------------------------------------------------------------------------------------------
# segment and pattern matching
# ---------------------------------------------------------------------------------------------

@dataclass
class SegResult:
    ok: bool
    count: int                                   # elements matched (prefix length)
    start: int
    end: int                                     # index after the last matched line
    positions: List[int] = field(default_factory=list)
    skipped: List[List[int]] = field(default_factory=list)   # skipped[k]: blank lines skipped after element k
    fail_index: int = -1                         # file index compared against the failing element


def match_segment(seg: List[PatEl], cmp: Comparator, start: int, ibl: bool) -> SegResult:
    """Match one segment as a unit starting at `start` (§7.3, §8.2 step 4).

    Under --ignore-blank-lines (§5.1) blank/whitespace-only file lines between elements are
    skipped unless the next element is a `-` line equal to that line; the first element must
    match at `start` itself (a candidate never starts on a skipped line)."""
    i = start
    positions: List[int] = []
    skipped: List[List[int]] = []
    for k, pe in enumerate(seg):
        if k > 0:
            here: List[int] = []
            if ibl:
                while i < cmp.n and cmp.is_blank(i) and not (pe.is_minus and cmp.eq(pe, i)):
                    here.append(i)
                    i += 1
            skipped.append(here)
        if not cmp.eq(pe, i):
            return SegResult(False, k, start, i, positions, skipped, fail_index=i)
        positions.append(i)
        i += 1
    skipped.append([])     # nothing is skipped after the last element: trailing blanks are outside
    return SegResult(True, len(seg), start, i, positions, skipped)


@dataclass
class Match:
    start: int
    end: int
    segs: List[SegResult]
    level: str = LEVEL_EXACT
    sigma: Optional[Dict[bytes, bytes]] = None
    prefix_sub: Optional[Tuple[bytes, bytes]] = None

    def positions_of(self, pattern: Pattern) -> Dict[int, Tuple[int, List[int]]]:
        """id(BodyElement) → (file index, blank lines skipped after it)."""
        out: Dict[int, Tuple[int, List[int]]] = {}
        for seg, res in zip(pattern.segments, self.segs):
            for k, pe in enumerate(seg):
                out[id(pe.elem)] = (res.positions[k], res.skipped[k])
        return out


@dataclass
class ChainFailure:
    segment: int          # 0-based index of the segment that failed
    prev_end: int         # where the previous segment ended (for segment > 0)
    first: Optional[SegResult] = None


class PatternMatcher:
    """All matching of one pattern against one file state at one level."""

    def __init__(self, pattern: Pattern, cmp: Comparator, ibl: bool) -> None:
        self.pattern = pattern
        self.cmp = cmp
        self.ibl = ibl
        self._unit_positions: Dict[int, List[int]] = {}

    def unit_positions(self, k: int) -> List[int]:
        """Sorted start positions where segment k matches as a unit (independent of p)."""
        pos = self._unit_positions.get(k)
        if pos is None:
            seg = self.pattern.segments[k]
            pos = [q for q in range(self.cmp.n) if match_segment(seg, self.cmp, q, self.ibl).ok]
            self._unit_positions[k] = pos
        return pos

    def match_at(self, p: int):
        """Match the whole pattern from p. Returns Match or ChainFailure (§7.3: each following segment
        is matched at its first full match after the previous one; no backtracking)."""
        segs = self.pattern.segments
        first = match_segment(segs[0], self.cmp, p, self.ibl)
        if not first.ok:
            return ChainFailure(0, p, first)
        results = [first]
        prev_end = first.end
        for k in range(1, len(segs)):
            pos = self.unit_positions(k)
            j = bisect.bisect_left(pos, prev_end)
            if j >= len(pos):
                return ChainFailure(k, prev_end, first)
            res = match_segment(segs[k], self.cmp, pos[j], self.ibl)
            results.append(res)
            prev_end = res.end
        return Match(p, prev_end, results, level=self.cmp.level)

    def matches_from(self, lo: int, hi: Optional[int] = None) -> List[Match]:
        """All matches with start in [lo, hi) (overlapping matches included, §8.2 step 6)."""
        hi = self.cmp.n if hi is None else min(hi, self.cmp.n)
        out = []
        for p in range(max(lo, 0), hi):
            m = self.match_at(p)
            if isinstance(m, Match):
                out.append(m)
        return out


# ---------------------------------------------------------------------------------------------
# level (b): re-indentation σ (§8.2 step 5)
# ---------------------------------------------------------------------------------------------

@dataclass
class SigmaResult:
    ok: bool
    sigma: Optional[Dict[bytes, bytes]] = None
    prefix_sub: Optional[Tuple[bytes, bytes]] = None
    refused_plus: Optional[BodyElement] = None    # `+` line outside the domain (E410 must name it)


def compute_sigma(match: Match, pattern: Pattern, lines: List[FileLine], plus_elems: List[BodyElement]) -> SigmaResult:
    sigma: Dict[bytes, bytes] = {}
    for seg, res in zip(pattern.segments, match.segs):
        for k, pe in enumerate(seg):
            ia, ra = cmpmod.split_indent(cmpmod.strip_trailing(pe.data))
            if not ra:
                continue                      # blank and whitespace-only lines take no part in σ
            fi = cmpmod.split_indent(cmpmod.strip_trailing(lines[res.positions[k]].content))[0]
            if ia in sigma and sigma[ia] != fi:
                return SigmaResult(False)     # not a function
            sigma[ia] = fi
    if not sigma or all(k == v for k, v in sigma.items()):
        return SigmaResult(False)             # identity: that is level (a)
    prefix_sub = _prefix_substitution(sigma)
    for e in plus_elems:
        data = e.content.encode("utf-8")
        if cmpmod.is_blank_bytes(data):
            continue
        ind = cmpmod.split_indent(data)[0]
        if ind in sigma:
            continue
        if prefix_sub is not None and ind.startswith(prefix_sub[0]):
            continue
        return SigmaResult(False, sigma, prefix_sub, refused_plus=e)
    return SigmaResult(True, sigma, prefix_sub)


def _prefix_substitution(sigma: Dict[bytes, bytes]) -> Optional[Tuple[bytes, bytes]]:
    """σ is a single prefix substitution X → Y when removing from every pair its longest common
    suffix yields the same (X, Y) with X ≠ Y, and every domain indent starts with X."""
    reduced = set()
    for x, y in sigma.items():
        k = 0
        while k < len(x) and k < len(y) and x[len(x) - 1 - k] == y[len(y) - 1 - k]:
            k += 1
        reduced.add((x[:len(x) - k], y[:len(y) - k]))
    if len(reduced) != 1:
        return None
    X, Y = reduced.pop()
    if X == Y or not all(d.startswith(X) for d in sigma):
        return None
    return X, Y


def reindent(content: bytes, match: Match) -> bytes:
    """Apply σ (or the prefix substitution) to a `+` line (§8.2 step 5 level (b))."""
    if match.sigma is None or cmpmod.is_blank_bytes(content):
        return content
    ind, rest = cmpmod.split_indent(content)
    if ind in match.sigma:
        return match.sigma[ind] + rest
    if match.prefix_sub is not None and ind.startswith(match.prefix_sub[0]):
        X, Y = match.prefix_sub
        return Y + ind[len(X):] + rest
    return content


# ---------------------------------------------------------------------------------------------
# candidates at the levels of §8.2 step 5
# ---------------------------------------------------------------------------------------------

@dataclass
class LevelOutcome:
    level: Optional[str]
    candidates: List[Match]
    matcher: Optional[PatternMatcher]
    refused_plus: Optional[BodyElement] = None     # level (b) failed only because of this `+` line


def levels_for(opts: MatchOptions) -> List[str]:
    out = [LEVEL_EXACT]
    if opts.indent_shift:
        out.append(LEVEL_INDENT)
    if opts.lenient:
        out.append(LEVEL_LENIENT)
    return out


def find_candidates(pattern: Pattern, lines: List[FileLine], opts: MatchOptions, hunk: Hunk,
                    lo: int, levels: Optional[List[str]] = None) -> LevelOutcome:
    """Candidates ≥ lo at the first level that yields at least one (§8.2 step 5)."""
    plus_elems = [e for e in hunk.elements if e.kind == PLUS]
    refused: Optional[BodyElement] = None
    for level in (levels or levels_for(opts)):
        pm = PatternMatcher(pattern, Comparator(lines, opts, level), opts.ignore_blank_lines)
        raw = pm.matches_from(lo)
        if level == LEVEL_INDENT:
            good = []
            refusals: List[BodyElement] = []
            for m in raw:
                sr = compute_sigma(m, pattern, lines, plus_elems)
                if sr.ok:
                    m.sigma, m.prefix_sub = sr.sigma, sr.prefix_sub
                    good.append(m)
                elif sr.refused_plus is not None:
                    refusals.append(sr.refused_plus)
            # "If level (b) fails everywhere only because of a `+` line outside the domain, the E410
            # diagnostic MUST say so and name that line": every position whose rests matched was
            # refused for that reason.
            if not good and raw and len(refusals) == len(raw):
                refused = refusals[0]
            raw = good
        if raw:
            return LevelOutcome(level, raw, pm, refused)
    return LevelOutcome(None, [], None, refused)


# ---------------------------------------------------------------------------------------------
# W511 (§7.3)
# ---------------------------------------------------------------------------------------------

@dataclass
class W511Finding:
    segment: int          # 1-based segment ordinal
    chosen: int           # 0-based start of the segment's chosen match
    later: int            # 0-based first later start


def w511_findings(match: Match, pm: PatternMatcher) -> List[W511Finding]:
    """For every segment after the first that ends with a `-` line: would it also match as a unit
    at any start from the line after the end of its chosen match to the end of file?"""
    out = []
    segs = pm.pattern.segments
    for k in range(1, len(segs)):
        if not segs[k] or not segs[k][-1].is_minus:
            continue
        res = match.segs[k]
        pos = pm.unit_positions(k)
        j = bisect.bisect_left(pos, res.end)
        if j < len(pos):
            out.append(W511Finding(k + 1, res.start, pos[j]))
    return out
