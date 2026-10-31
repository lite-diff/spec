"""In-memory file-system state and the write phase (§8.1, §8.5, §8.6 atomicity).

Blocks are evaluated against the in-memory state produced by the earlier blocks; nothing is
written until every block has succeeded. The write phase writes each file to a temporary file
in the same directory and renames it over the target (os.replace).
"""
from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional, Tuple

from .paths import components


class Workspace:
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        # canonical path → content bytes, or None for "deleted"
        self.overlay: Dict[str, Optional[bytes]] = {}
        self.order: List[str] = []         # paths in order of first change (for `written`)

    # ------------------------------------------------------------------ path mapping

    def disk_path(self, path: str) -> str:
        """Canonical "/" path → OS path under the workspace root (§6.3.6: OS separators)."""
        return os.path.join(self.root, *components(path))

    # ------------------------------------------------------------------ queries

    def is_symlink(self, path: str) -> bool:
        """§6.3.3 E103: the path, or any directory on the way to it, is a symbolic link on disk."""
        if path in self.overlay:
            return False
        cur = self.root
        for comp in components(path):
            cur = os.path.join(cur, comp)
            # a Windows junction is a link for this purpose too (Python 3.12+: os.path.isjunction)
            if os.path.islink(cur) or getattr(os.path, "isjunction", lambda _p: False)(cur):
                return True
            if not os.path.exists(cur):
                return False
        return False

    def is_file(self, path: str) -> bool:
        """A regular file exists at the path (in the current in-memory state)."""
        if path in self.overlay:
            return self.overlay[path] is not None
        return os.path.isfile(self.disk_path(path))

    def exists(self, path: str) -> bool:
        """Anything (file or directory) exists at the path."""
        if path in self.overlay:
            if self.overlay[path] is not None:
                return True
            return False
        if os.path.lexists(self.disk_path(path)):
            return True
        # a directory implied by a file created earlier in this document
        prefix = path.rstrip("/") + "/"
        return any(p.startswith(prefix) and v is not None for p, v in self.overlay.items())

    def read(self, path: str) -> bytes:
        if path in self.overlay:
            data = self.overlay[path]
            assert data is not None
            return data
        with open(self.disk_path(path), "rb") as f:
            return f.read()

    # ------------------------------------------------------------------ changes (in memory)

    def _touch(self, path: str) -> None:
        if path not in self.order:
            self.order.append(path)

    def write(self, path: str, data: bytes) -> None:
        self.overlay[path] = data
        self._touch(path)

    def delete(self, path: str) -> None:
        self.overlay[path] = None
        self._touch(path)

    # ------------------------------------------------------------------ write phase

    def commit(self) -> Tuple[List[str], Optional[str]]:
        """Write every change to disk. Returns (paths written/deleted, error message or None).

        Writes come first (temp file + rename), deletions last, so that a rename never loses the
        source before the target exists. Directories left empty by a delete or a rename are removed
        (§6.4.3 step 3 SHOULD, §12 item 31); they are not listed in `written` (MAY)."""
        done: List[str] = []
        current = None
        try:
            for path in self.order:
                data = self.overlay[path]
                if data is None:
                    continue
                if os.path.isfile(self.disk_path(path)) and self._same(path, data):
                    continue
                current = path
                self._atomic_write(path, data)
                done.append(path)
            for path in self.order:
                if self.overlay[path] is None:
                    dp = self.disk_path(path)
                    if os.path.lexists(dp):
                        current = path
                        os.remove(dp)
                        done.append(path)
                        self._remove_empty_parents(dp)
        except OSError as e:
            # Appendix B `writeError`: the failing path and the files already written
            return done, ("write phase failed at %r after %d change(s) (%s): %s"
                          % (current, len(done), ", ".join(done) or "none written", e))
        return done, None

    def _remove_empty_parents(self, disk_path: str) -> None:
        d = os.path.dirname(disk_path)
        while os.path.normcase(os.path.abspath(d)) != os.path.normcase(self.root) and d.startswith(self.root):
            try:
                if os.path.islink(d) or os.listdir(d):
                    return
                os.rmdir(d)
            except OSError:
                return
            d = os.path.dirname(d)

    def _same(self, path: str, data: bytes) -> bool:
        try:
            with open(self.disk_path(path), "rb") as f:
                return f.read() == data
        except OSError:
            return False

    def _atomic_write(self, path: str, data: bytes) -> None:
        dp = self.disk_path(path)
        directory = os.path.dirname(dp)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".litediff-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dp)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
