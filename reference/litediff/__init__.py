"""lite-diff v1.1 reference implementation.

Public API:
    apply(patch: bytes, workdir: str, check=False, strict=False) -> dict   # Appendix B result
"""
from __future__ import annotations

from typing import Any, Dict

__version__ = "1.1.0"


def apply(patch: bytes, workdir: str, check: bool = False, strict: bool = False) -> Dict[str, Any]:
    from .engine import apply_document
    from .parser import HostOptions
    from .result import build_result

    return build_result(apply_document(patch, workdir, HostOptions(check=check, strict=strict)))
