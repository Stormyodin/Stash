"""Tiny allocation-light fuzzy matcher (subsequence + bonuses), returns matched indices for highlighting."""
from __future__ import annotations

_SEPS = frozenset(" -_./\\()[]")


def match(query: str, text: str) -> tuple[int, tuple[int, ...]] | None:
    """Score ``text`` against lowercase ``query``. Higher is better; None = no match."""
    if not query:
        return 0, ()
    t = text.lower()
    # Fast path: contiguous substring (best kind of match)
    pos = t.find(query)
    if pos >= 0:
        score = 100 + len(query) * 4 - min(pos, 30)
        if pos == 0 or t[pos - 1] in _SEPS:
            score += 40
        if len(query) == len(t):
            score += 50
        return score, tuple(range(pos, pos + len(query)))
    # Subsequence with consecutive / word-boundary bonuses
    idx: list[int] = []
    score = 0
    ti = 0
    prev = -2
    n = len(t)
    for ch in query:
        found = t.find(ch, ti)
        if found < 0:
            return None
        if found == prev + 1:
            score += 8
        if found == 0 or t[found - 1] in _SEPS:
            score += 10
        score -= min(found - ti, 6)
        idx.append(found)
        prev = found
        ti = found + 1
        if ti > n:
            return None
    return score, tuple(idx)


def match_entry(query: str, name: str, publisher: str, path: str):
    """Match against name (highlightable) then publisher/path (lower weight, no highlight)."""
    m = match(query, name)
    if m is not None:
        return m[0] + 50, m[1]
    if publisher:
        m = match(query, publisher)
        if m is not None:
            return m[0] - 50, ()
    # Paths are long and would subsequence-match almost anything: substring only.
    if path and query in path.lower():
        return 20, ()
    return None
