"""Content of match-phase diagnostics (§8.2 step 5, §8.6 "Diagnostic content for matching errors").

E410: best candidate (longest matching prefix at level (a), or the Levenshtein-closest line with
the `noLineMatched` flag), the failing anchor element and the file line it was compared with,
rendered with visible whitespace, the difference classification, the --ignore-all-space test,
the "already applied" statement, and for boundary blocks the failing segment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import compare as cmpmod
from .diagnostics import visible, visible_bytes
from .matcher import (LEVEL_EXACT, ChainFailure, Comparator, Match, PatEl, Pattern, PatternMatcher,
                      match_segment)
from .model import BodyElement, Hunk
from .options import MatchOptions
from .textfile import FileLine

CLASS_TEXT = {
    "leading-whitespace": "leading whitespace only",
    "tabs-vs-spaces": "tabs versus spaces",
    "internal-whitespace": "internal whitespace",
    "other": "other (content differs)",
}


def neighbor_lines(lines: List[FileLine], start: int, end: int) -> Dict[str, str]:
    """§8.6 E414/W410 SHOULD: the file line before and after a match, whitespace made visible."""
    out: Dict[str, str] = {}
    out["before"] = visible_bytes(lines[start - 1].content) if start - 1 >= 0 else "(start of file)"
    out["after"] = visible_bytes(lines[end].content) if end < len(lines) else "(end of file)"
    return out


def context_lines(lines: List[FileLine], at: int, radius: int = 2) -> List[str]:
    lo, hi = max(0, at - radius), min(len(lines), at + radius + 1)
    return ["%d: %s" % (k + 1, visible_bytes(lines[k].content)) for k in range(lo, hi)]


@dataclass
class _Best:
    start: int                     # 0-based start of the best candidate
    failed: PatEl                  # anchor element that failed there
    compared: Optional[int]        # 0-based file index it was compared with (None: end of file)
    no_line_matched: bool = False
    segment: Optional[int] = None  # 1-based failing segment (boundary blocks)
    prev_end: Optional[int] = None


def _longest_prefix(seg: List[PatEl], cmp: Comparator, lo: int, ibl: bool):
    best = None
    for q in range(lo, cmp.n):
        r = match_segment(seg, cmp, q, ibl)
        if best is None or r.count > best[1]:
            best = (q, r.count, r.fail_index)
        if r.count == len(seg):
            break
    return best


def _closest(seg: List[PatEl], lines: List[FileLine], lo: int) -> Optional[int]:
    """Smallest Levenshtein distance to the first element's content (ties → earliest)."""
    if lo >= len(lines):
        return None
    target = cmpmod.strip_trailing(seg[0].data).decode("utf-8", "replace")
    best, best_d = None, None
    for k in range(lo, len(lines)):
        d = cmpmod.levenshtein(target, cmpmod.strip_trailing(lines[k].content).decode("utf-8", "replace"))
        if best_d is None or d < best_d:
            best, best_d = k, d
    return best


def find_best(pattern: Pattern, lines: List[FileLine], opts: MatchOptions, S: int) -> Optional[_Best]:
    ibl = opts.ignore_blank_lines
    cmp = Comparator(lines, opts, LEVEL_EXACT)
    segs = pattern.segments
    pm = PatternMatcher(pattern, cmp, ibl)
    if len(segs) > 1:
        # §7.3: the first segment's earliest match and the first segment after it that failed
        for p in range(S, cmp.n):
            if match_segment(segs[0], cmp, p, ibl).ok:
                res = pm.match_at(p)
                if isinstance(res, ChainFailure) and res.segment > 0:
                    # §8.2 step 5 "Best candidate" (§12 item 18): the file line compared against
                    # for the failing segment is the line at the position where the segment was
                    # tried, i.e. the first line after the end of the previous segment's match.
                    # The segment is compared from there; the failing element is the first one that
                    # does not match (the segment's first element unless a prefix matched there).
                    # The best candidate itself is the first segment's match, not chosen by edit
                    # distance, so `noLineMatched` stays false.
                    seg = segs[res.segment]
                    r = match_segment(seg, cmp, res.prev_end, ibl)
                    k = min(r.count, len(seg) - 1)
                    compared = r.fail_index if (not r.ok and r.fail_index < cmp.n) else None
                    return _Best(p, seg[k], compared, no_line_matched=False, segment=res.segment + 1,
                                 prev_end=res.prev_end)
                break
    seg0 = segs[0]
    lp = _longest_prefix(seg0, cmp, S, ibl)
    if lp is not None and lp[1] > 0:
        if lp[1] >= len(seg0):          # cannot happen for a failed single-segment pattern
            return _Best(lp[0], seg0[-1], None, segment=1 if len(segs) > 1 else None)
        return _Best(lp[0], seg0[lp[1]], lp[2] if lp[2] < cmp.n else None,
                     segment=1 if len(segs) > 1 else None)
    k = _closest(seg0, lines, S)
    if k is None:
        return None
    return _Best(k, seg0[0], k, no_line_matched=True, segment=1 if len(segs) > 1 else None)


def e410_content(hunk: Hunk, pattern: Pattern, lines: List[FileLine], opts: MatchOptions, S: int,
                 cursor: int, already_at: Optional[int], refused_plus: Optional[BodyElement],
                 scope_line: Optional[int]) -> Dict[str, Any]:
    """Returns {"message", "extra", "hint"} for an E410 diagnostic (§8.6)."""
    extra: Dict[str, Any] = {"searchStart": S + 1, "cursor": cursor + 1}
    first = pattern.elements[0] if pattern.elements else None
    parts = []
    if first is not None:
        parts.append("no match for the anchor pattern from line %d to the end of file (first anchor element: %s)"
                     % (S + 1, visible(first.elem.content)))
    else:
        parts.append("no match for the anchor pattern from line %d" % (S + 1))
    if scope_line is not None:
        parts.append("search started at the scope line %d" % (scope_line + 1))
    hint_parts: List[str] = []
    best = find_best(pattern, lines, opts, S) if first is not None else None
    if best is not None:
        anchor_bytes = best.failed.data
        file_bytes = lines[best.compared].content if best.compared is not None else b""
        cls = cmpmod.classify(anchor_bytes, file_bytes)
        all_space = PatternMatcher(pattern, Comparator(lines, opts.with_all_space(), LEVEL_EXACT),
                                   opts.ignore_blank_lines).match_at(best.start)
        would = isinstance(all_space, Match)
        bc: Dict[str, Any] = {
            "line": best.start + 1,
            "failedElementIndex": best.failed.anchor_index,
            "anchorText": visible(best.failed.elem.content),
            "fileText": visible_bytes(file_bytes) if best.compared is not None else "(end of file)",
            "classification": cls,
            "noLineMatched": best.no_line_matched,
            "wouldMatchIgnoringAllSpace": would,
            "appearsAlreadyAppliedAt": already_at + 1 if already_at is not None else None,
            "segment": best.segment,
            "context": context_lines(lines, best.start),
            "x-anchorPatchLine": best.failed.elem.line_no,
        }
        if best.compared is not None:
            bc["x-fileLine"] = best.compared + 1
        extra["bestCandidate"] = bc
        if best.no_line_matched:
            parts.append("no file line matched the first anchor element exactly; closest line %d"
                         % (best.start + 1))
        else:
            parts.append("best candidate at line %d" % (best.start + 1))
        parts.append("anchor element #%d `%s` (patch line %d) was compared with %s `%s`"
                     % (best.failed.anchor_index, bc["anchorText"], best.failed.elem.line_no,
                        "file line %d" % (best.compared + 1) if best.compared is not None else "the end of file",
                        bc["fileText"]))
        parts.append("difference: %s" % CLASS_TEXT[cls])
        if cls in ("leading-whitespace", "tabs-vs-spaces"):
            hint_parts.append("the hunk's `+` lines are probably indented the same way: re-read the file region "
                              "and resend the whole hunk with the file's indentation")
        parts.append("would match ignoring all whitespace: %s" % ("yes" if would else "no"))
        if best.segment is not None and best.prev_end is not None:
            parts.append("segment %d matches nowhere after line %d, where segment %d ended"
                         % (best.segment, best.prev_end, best.segment - 1))
        if best.failed.elem.content.startswith("-- "):
            hint_parts.append("the failing line starts with `-- `: a `+++` path header or a hunk header may be "
                              "missing (a `--- ` line followed by a body line is a deletion)")
    else:
        extra["bestCandidate"] = {"appearsAlreadyAppliedAt": already_at + 1 if already_at is not None else None,
                                  "noLineMatched": True}
        parts.append("there are no file lines from the search start")
    if already_at is not None:
        parts.append("hunk appears to be already applied at line %d" % (already_at + 1))
        hint_parts.append("drop the hunk if it is already applied (or use --skip-applied)")
    else:
        parts.append("the hunk does not appear to be already applied")
    if refused_plus is not None:
        parts.append("--indent-shift refused: the `+` line at patch line %d (%s) has an indentation outside the "
                     "re-indentation table" % (refused_plus.line_no, visible(refused_plus.content)))
        extra["x-indentShiftRefusedLine"] = refused_plus.line_no
    # §8.6: the classification advice, the "already applied" statement and the `-- ` hint are part
    # of the message (MUST/SHOULD); they are repeated in `hint` for hosts that show hints separately.
    message = "; ".join(parts + hint_parts)
    return {"message": message, "extra": extra, "hint": "; ".join(hint_parts) or None}
