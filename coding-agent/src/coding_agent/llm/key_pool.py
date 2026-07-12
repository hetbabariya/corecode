"""Round-robin API key pool with 429 rate-limit rotation."""

from __future__ import annotations


class KeyPool:
    """Manages multiple API keys with round-robin rotation.

    When a 429 is detected, call `rotate()` to move to the next key.
    When all keys have been tried (`is_exhausted`), the caller should
    back off and then call `reset()` before retrying.
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("KeyPool requires at least one key")
        self._keys = list(keys)
        self._index = 0
        self._exhausted = False

    def get_key(self) -> str:
        """Return the current key without advancing."""
        return self._keys[self._index]

    def rotate(self) -> str:
        """Advance to the next key and return it.

        Marks the pool as exhausted when wrapping back to the start.
        """
        next_index = (self._index + 1) % len(self._keys)
        if next_index <= self._index:
            self._exhausted = True
        self._index = next_index
        return self._keys[self._index]

    @property
    def is_exhausted(self) -> bool:
        """True when all keys in the pool have been tried at least once."""
        return self._exhausted

    def reset(self) -> None:
        """Reset the exhaustion flag so rotation can continue."""
        self._exhausted = False

    @property
    def size(self) -> int:
        """Number of keys in the pool."""
        return len(self._keys)

    @property
    def current_index(self) -> int:
        """Index of the currently active key."""
        return self._index

    def __repr__(self) -> str:
        return f"KeyPool(size={self.size}, index={self._index}, exhausted={self._exhausted})"
