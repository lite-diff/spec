"""Target file line model (§1.3 "Target file line model").

The content is bytes, split on LF or CRLF into (content bytes, terminator) pairs; only the
last line can be unterminated. An empty file has zero lines. A UTF-8 BOM is not part of the
first line and is preserved whatever happens to line 1. The final terminator follows git
semantics (§12 item 23): see `finalize`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

BOM = b"\xef\xbb\xbf"
LF = b"\n"
CRLF = b"\r\n"


@dataclass(eq=False)          # identity semantics: §1.3 asks whether "its original last line" is still last
class FileLine:
    content: bytes
    term: Optional[bytes]     # LF, CRLF, or None (unterminated last line)


@dataclass
class TextFile:
    lines: List[FileLine]
    bom: bool
    eol: bytes                       # §1.3 EOL convention for inserted lines
    original_unterminated: Optional[FileLine]   # the original unterminated last line, if any

    @staticmethod
    def parse(data: bytes, default_eol: bytes) -> "TextFile":
        bom = data.startswith(BOM)
        if bom:
            data = data[len(BOM):]
        lines: List[FileLine] = []
        start = 0
        while start < len(data):
            nl = data.find(b"\n", start)
            if nl < 0:
                lines.append(FileLine(data[start:], None))
                break
            if nl > start and data[nl - 1:nl] == b"\r":
                lines.append(FileLine(data[start:nl - 1], CRLF))
            else:
                lines.append(FileLine(data[start:nl], LF))
            start = nl + 1
        # EOL convention: the terminator of the first terminated line, else the default EOL
        eol = next((ln.term for ln in lines if ln.term is not None), default_eol)
        last = lines[-1] if lines and lines[-1].term is None else None
        return TextFile(lines=lines, bom=bom, eol=eol, original_unterminated=last)

    def new_line(self, content: bytes) -> FileLine:
        """An inserted line receives the file's EOL convention (§1.3 "Output")."""
        return FileLine(content, self.eol)

    def finalize(self, unterminated: Optional[bool]) -> None:
        """§1.3 "Final terminator" (§12 item 23, git semantics).

        `unterminated` is the decision of the new side of the last hunk that reached the end of file
        (True: a new-side sentinel was recorded; False: none was), or None when no hunk of the block
        reached the end of file: then the last line keeps its original terminator state (it is the
        original last line, untouched). Every line that is not last is terminated (a formerly
        unterminated last line followed by new lines gains the file's EOL convention)."""
        for ln in self.lines[:-1]:
            if ln.term is None:
                ln.term = self.eol
        if not self.lines or unterminated is None:
            return
        last = self.lines[-1]
        if unterminated:
            last.term = None
        elif last.term is None:
            last.term = self.eol

    def to_bytes(self) -> bytes:
        out = bytearray(BOM if self.bom else b"")
        for ln in self.lines:
            out += ln.content
            if ln.term is not None:
                out += ln.term
        return bytes(out)


def created_file(contents: List[bytes], eol: bytes, unterminated_last: bool) -> bytes:
    """§6.4.5: the created file is the sequence of `+` line contents, terminated unless the
    hunk ended with a sentinel. EOL = the default EOL (§1.3)."""
    out = bytearray()
    for k, c in enumerate(contents):
        out += c
        if not (unterminated_last and k == len(contents) - 1):
            out += eol
    return bytes(out)
