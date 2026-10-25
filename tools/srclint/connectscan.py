# SPDX-License-Identifier: GPL-2.0-or-later
"""Extract Qt connect(...) call sites from C++ source text.

A small hand-rolled scanner, not a C++ parser: connect() calls can span
multiple lines and their lambda argument contains its own parens/braces/
commas, so a plain regex can't reliably find the call's own closing paren
or split its top-level arguments. This does just enough -- paren-depth
tracking to find the matching close, and comma-splitting that respects
nested (), {}, <> -- to get the sender/signal/third-argument text apart,
which is all rule R-B needs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CONNECT_CALL = re.compile(r"(?<!\w)connect\s*\(")


@dataclass(frozen=True)
class ConnectCall:
    start_line: int  # 1-based line of the "connect(" token
    args: list[str]  # top-level, comma-split argument texts (stripped)
    raw: str


def _matching_close(text: str, open_index: int) -> int | None:
    """Index of the ')' matching the '(' at open_index, or None."""
    depth = 0
    i = open_index
    n = len(text)
    while i < n:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        # Skip over string/char literals so a ')' inside one doesn't
        # unbalance the count.
        elif c in "\"'":
            quote = c
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        i += 1
    return None


def _split_top_level(args_text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = []
    i = 0
    n = len(args_text)
    while i < n:
        c = args_text[i]
        if c in "([{":
            depth += 1
            current.append(c)
        elif c in ")]}":
            depth -= 1
            current.append(c)
        elif c in "\"'":
            quote = c
            current.append(c)
            i += 1
            while i < n and args_text[i] != quote:
                current.append(args_text[i])
                if args_text[i] == "\\" and i + 1 < n:
                    i += 1
                    current.append(args_text[i])
                i += 1
            if i < n:
                current.append(args_text[i])
        elif c == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def find_connect_calls(text: str) -> list[ConnectCall]:
    calls = []
    for m in _CONNECT_CALL.finditer(text):
        open_idx = m.end() - 1
        close_idx = _matching_close(text, open_idx)
        if close_idx is None:
            continue
        inner = text[open_idx + 1 : close_idx]
        args = _split_top_level(inner)
        start_line = text.count("\n", 0, m.start()) + 1
        calls.append(ConnectCall(start_line=start_line, args=args, raw=text[m.start() : close_idx + 1]))
    return calls


_CAPTURE_LIST = re.compile(r"^\[([^\]]*)\]")
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


def lambda_capture_list(arg: str) -> list[str] | None:
    """If @p arg looks like a lambda literal, its capture identifiers; else None."""
    arg = arg.strip()
    m = _CAPTURE_LIST.match(arg)
    if not m:
        return None
    # Must be followed by "(" (params) or "{" (body) to actually be a lambda,
    # not e.g. an array-subscript expression (which connect() never takes
    # as a top-level argument, but keep the check honest).
    rest = arg[m.end() :].lstrip()
    if not rest.startswith("(") and not rest.startswith("{"):
        return None
    captures = [c.strip() for c in m.group(1).split(",") if c.strip()]
    return captures


def captures_this(arg: str) -> bool:
    captures = lambda_capture_list(arg)
    if captures is None:
        return False
    return any(c == "this" for c in captures)
