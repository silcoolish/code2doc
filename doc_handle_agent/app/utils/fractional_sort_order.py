"""Fractional indexing sort key generator.

Aligns with workspace-service FractionalSortOrder utility.
Uses A-Z uppercase strings as sparse sort keys.
"""

_MIN_CHAR = ord("A")
_MAX_CHAR = ord("Z")
_RADIX = _MAX_CHAR - _MIN_CHAR + 1
_DEFAULT_KEY_LENGTH = 8
_MAX_KEY_LENGTH = 500


def first() -> str:
    """Return the default first sort key."""
    return "I" * _DEFAULT_KEY_LENGTH


def key_for_index(index: int) -> str:
    """Generate a sparse sort key for a sequential index (0-based)."""
    if index <= 0:
        return first()
    current = first()
    for _ in range(index):
        current = between(current, None)
    return current


def between(before: str | None, after: str | None) -> str:
    """Generate a sort key strictly between *before* and *after*.

    Raises:
        ValueError: if the key space is exhausted.
    """
    norm_before = _normalize(before)
    norm_after = _normalize(after)
    if norm_before is not None and norm_after is not None and norm_before >= norm_after:
        raise ValueError("before must be less than after")

    for length in range(_DEFAULT_KEY_LENGTH, _MAX_KEY_LENGTH + 1):
        lower = (
            0
            if norm_before is None
            else _to_number(_pad_right(norm_before, length, "A"))
        )
        upper = (
            _max_number(length)
            if norm_after is None
            else _to_number(_pad_right(norm_after, length, "A"))
        )
        if upper - lower > 1:
            middle = (lower + upper) // 2
            candidate = _from_number(middle, length)
            if (norm_before is None or candidate > norm_before) and (
                norm_after is None or candidate < norm_after
            ):
                return candidate

    raise ValueError("sort key space exhausted")


def normalize_or_null(value: str | None) -> str | None:
    """Return normalized key or None if invalid/empty."""
    return _normalize(value)


def _normalize(value: str | None) -> str | None:
    if not value:
        return None
    trimmed = value.strip().upper()
    for ch in trimmed:
        if ch < "A" or ch > "Z":
            return None
    return trimmed[:_MAX_KEY_LENGTH] if len(trimmed) > _MAX_KEY_LENGTH else trimmed


def _to_number(value: str) -> int:
    result = 0
    for ch in value:
        result = result * _RADIX + (ord(ch) - _MIN_CHAR)
    return result


def _from_number(number: int, length: int) -> str:
    chars = []
    current = number
    for _ in range(length):
        current, remainder = divmod(current, _RADIX)
        chars.append(chr(_MIN_CHAR + remainder))
    return "".join(reversed(chars))


def _max_number(length: int) -> int:
    return _RADIX**length - 1


def _pad_right(value: str, length: int, fill_char: str) -> str:
    if len(value) >= length:
        return value[:length]
    return value + fill_char * (length - len(value))
