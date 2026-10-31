"""The machine-readable result of §8.6 in the shape of Appendix B."""
from __future__ import annotations

from typing import Any, Dict

from .engine import Engine


def build_result(engine: Engine) -> Dict[str, Any]:
    doc, opts = engine.doc, engine.opts
    blocks = []
    for b in doc.blocks:
        out = engine.outcomes[b.ordinal]
        hunks = []
        for h, ho in zip(b.hunks, out.hunks):
            hj: Dict[str, Any] = {"ordinal": h.ordinal, "header": h.header.kind, "status": ho.status}
            if ho.status in ("applied", "checked", "matched") and ho.applied_range is not None:
                hj["appliedRange"] = {"firstLine": ho.applied_range[0], "lineCount": ho.applied_range[1]}
                if len(ho.all_ranges) > 1:      # --apply-all-matches: every application
                    hj["x-appliedRanges"] = [{"firstLine": a, "lineCount": c} for a, c in ho.all_ranges]
            if ho.level is not None and ho.status in ("applied", "checked", "matched"):
                hj["level"] = ho.level
            if ho.scope_line is not None:
                hj["scopeLine"] = ho.scope_line
            hj["x-patchLine"] = h.header_line_no
            hunks.append(hj)
        bj: Dict[str, Any] = {
            "ordinal": b.ordinal,
            "source": b.source,
            "target": b.target,
            "operation": b.operation,
            "status": out.status,
            "options": b.match_options.to_json(),
            "hunks": hunks,
            "x-patchLine": b.start_line,
        }
        blocks.append(bj)
    result: Dict[str, Any] = {
        "liteDiffVersion": opts.version,
        "status": engine.status,
        "options": opts.to_json(),
        "blocks": blocks,
        "diagnostics": [d.to_json() for d in engine.diags.items],
        "written": list(engine.written) if engine.status == "applied" else [],
    }
    if engine.check:
        # Appendix B (§12 item 33): later block statuses were computed with the failed blocks skipped
        result["checkedWithSkips"] = engine.checked_with_skips
    if engine.write_error:
        # Appendix B `writeError` (§12 item 34): the failing path and the files already written
        result["writeError"] = engine.write_error
        result["x-writtenBeforeError"] = list(engine.written)
    return result
