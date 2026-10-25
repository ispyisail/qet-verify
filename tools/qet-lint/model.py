# SPDX-License-Identifier: GPL-2.0-or-later
"""Light DOM shared by every qet-lint rule: parse each file exactly once.

The rules operate on two views of one file:

  * ``raw`` -- the file's bytes, for the control-character rules (P002/E002)
    which must see bytes the XML parser would never hand back.
  * ``tree`` -- the parsed ElementTree root, for the semantic rules (P001/
    P003/E001), or ``None`` with ``parse_error`` set when the file is not
    well-formed XML.

Line numbers are computed from ``raw`` (newline offsets), because
ElementTree does not track source positions and we want the report to point
at the offending byte, not at the element.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# XML 1.0 forbids these control code points outright: U+0000..0008, U+000B,
# U+000C, U+000E..001F. The only legal ASCII controls are U+0009 (tab),
# U+000A (LF) and U+000D (CR). In UTF-8 every one of these maps to a single
# byte with the same value, and none of these byte values can occur inside a
# multi-byte sequence, so a raw byte scan is an encoding-independent way to
# find them.
_ILLEGAL_CONTROL_BYTES = frozenset(
    set(range(0x00, 0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x20))
)

# A numeric character reference (&#11; / &#x0B;) that *resolves* to an illegal
# control code point is itself illegal XML 1.0 -- Qt's QDomDocument::setContent
# segfaults on it and Python's ElementTree rejects it ("reference to invalid
# character number"). A raw-byte scan alone cannot see it (the file contains
# the six ASCII characters "&#11;", not a 0x0B byte), so the scanner handles
# both forms.
_CHARREF_RE = re.compile(rb"&#(x?[0-9A-Fa-f]+);")


@dataclass
class ControlChar:
    """One illegal control character found in a file."""
    offset: int      # byte offset of the raw byte, or of the '&' of a reference
    code_point: int  # the U+00xx code point
    form: str        # "raw" or "charref"


def control_char_offsets(raw: bytes) -> list[ControlChar]:
    """Offsets of every illegal XML 1.0 control character in ``raw``.

    Covers raw control bytes and numeric character references to illegal code
    points. P002 and E002 are the same scan applied to .qet and .elmt files
    respectively (brief W2-stage1: "E002 ... same scan as P002").
    """
    out: list[ControlChar] = []
    for i, b in enumerate(raw):
        if b in _ILLEGAL_CONTROL_BYTES:
            out.append(ControlChar(i, b, "raw"))
    for m in _CHARREF_RE.finditer(raw):
        grp = m.group(1)
        try:
            cp = int(grp[1:], 16) if grp[:1] in (b"x", b"X") else int(grp)
        except ValueError:
            continue
        if cp in _ILLEGAL_CONTROL_BYTES:
            out.append(ControlChar(m.start(), cp, "charref"))
    out.sort(key=lambda c: c.offset)
    return out


@dataclass
class Document:
    """One .qet or .elmt file, parsed once for all rules."""

    path: Path                 # path as given on the command line
    display_path: str          # normalised path used in reports and baselines
    raw: bytes                 # file bytes
    tree: ET.Element | None = None
    parse_error: str | None = None

    _text: str | None = field(default=None, init=False, repr=False)
    _newlines: list[int] = field(default=None, init=False, repr=False)

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self.raw.decode("utf-8", errors="replace")
        return self._text

    def line_of_offset(self, offset: int) -> int:
        """1-based line number containing byte ``offset``."""
        if self._newlines is None:
            self._newlines = [i for i, b in enumerate(self.raw) if b == 0x0A]
        return bisect.bisect_right(self._newlines, offset) + 1

    def lines_of_uuid(self, uuid: str) -> list[int]:
        """1-based line numbers of every line containing ``uuid="<uuid>"``."""
        needle = f'uuid="{uuid}"'
        return [i for i, line in enumerate(self.text.splitlines(), 1)
                if needle in line]

    def line_of_attr(self, uuid: str, field: str, raw_value: str) -> int:
        """Line number of the element carrying ``field="<raw_value>"``.

        Used to give P001 violations (found by simulator.canon, which reports
        no line number) a source position. ``uuid`` disambiguates when several
        elements share the same bad value.
        """
        token = f'{field}="{raw_value}"'
        for i, line in enumerate(self.text.splitlines(), 1):
            if token in line and (not uuid or f'uuid="{uuid}"' in line):
                return i
        return 0


def load(path: Path, display_path: str | None = None) -> Document:
    """Read and parse ``path`` into a Document."""
    raw = path.read_bytes()
    tree = None
    parse_error = None
    try:
        tree = ET.parse(str(path)).getroot()
    except ET.ParseError as e:
        parse_error = str(e)
    return Document(
        path=path,
        display_path=display_path if display_path is not None else str(path),
        raw=raw,
        tree=tree,
        parse_error=parse_error,
    )
