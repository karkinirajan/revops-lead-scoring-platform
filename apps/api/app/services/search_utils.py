"""Helpers for building LIKE patterns from user text."""

LIKE_ESCAPE = "\\"


def contains_pattern(text: str) -> str:
    """A LIKE pattern that matches `text` anywhere, with `%`, `_` and the escape character in it taken literally (use with `escape=LIKE_ESCAPE`)."""
    escaped = text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_")
    return f"%{escaped}%"
