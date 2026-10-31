"""Change application in the anchor block (§8.3): the output sequence.

The anchor block found by the matcher is replaced by the output sequence, built by walking the
hunk body top to bottom:

    context / blank line  → the matched file line, unchanged
    `-` line              → nothing
    `...` marker          → nothing (captured lines are dropped)
    `+` line              → the line content (re-indented by σ at level (b))

Under --ignore-blank-lines, file lines skipped during matching are emitted unchanged
immediately after the contribution of the anchor element that matched the file line preceding
them and after any `+` lines that directly follow that anchor element in the body.
"""
from __future__ import annotations

from typing import List, Tuple

from .matcher import Match, Pattern, reindent
from .model import BLANK, CONTEXT, PLUS, Hunk
from .textfile import FileLine, TextFile


def output_sequence(hunk: Hunk, pattern: Pattern, match: Match, tf: TextFile) -> List[FileLine]:
    positions = match.positions_of(pattern)
    out: List[FileLine] = []
    pending: List[int] = []          # skipped blank lines waiting after the previous anchor element
    for e in hunk.elements:
        if e.kind == PLUS:
            out.append(tf.new_line(reindent(e.content.encode("utf-8"), match)))
            continue
        # any anchor element (or a blank context removed by --ignore-blank-lines) ends the run of
        # `+` lines that "directly follow" the previous anchor element
        out.extend(tf.lines[i] for i in pending)
        pending = []
        located = positions.get(id(e))
        if located is None:
            continue                 # `...` marker, or blank context removed from the pattern (§8.3)
        file_index, skipped_after = located
        if e.kind in (CONTEXT, BLANK):
            out.append(tf.lines[file_index])      # the original file line, not the patch line
        # MINUS: contributes nothing
        pending = list(skipped_after)
    out.extend(tf.lines[i] for i in pending)
    return out


def apply_match(hunk: Hunk, pattern: Pattern, match: Match, tf: TextFile) -> Tuple[int, int, int]:
    """Replace the anchor block [match.start, match.end) by the output sequence.

    Returns (start, len(output sequence), len(anchor block))."""
    out = output_sequence(hunk, pattern, match, tf)
    anchor_len = match.end - match.start
    tf.lines[match.start:match.end] = out
    return match.start, len(out), anchor_len


def apply_insertion(hunk: Hunk, tf: TextFile, at: int) -> Tuple[int, int]:
    """`@@ BOF` / `@@ EOF`: the `+` lines inserted at `at` (§8.3, §8.2 step 3)."""
    out = [tf.new_line(e.content.encode("utf-8")) for e in hunk.elements if e.kind == PLUS]
    tf.lines[at:at] = out
    return at, len(out)
