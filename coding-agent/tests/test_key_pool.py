"""Tests for the API key pool."""

from __future__ import annotations

import pytest

from coding_agent.llm.key_pool import KeyPool


class TestKeyPoolInit:
    def test_single_key(self) -> None:
        pool = KeyPool(["key1"])
        assert pool.size == 1
        assert pool.get_key() == "key1"
        assert pool.current_index == 0
        assert not pool.is_exhausted

    def test_multiple_keys(self) -> None:
        pool = KeyPool(["k1", "k2", "k3"])
        assert pool.size == 3
        assert pool.get_key() == "k1"

    def test_empty_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one key"):
            KeyPool([])


class TestKeyPoolRotation:
    def test_rotate_single_key(self) -> None:
        pool = KeyPool(["only"])
        result = pool.rotate()
        assert result == "only"
        assert pool.current_index == 0
        assert pool.is_exhausted  # wrapped back to 0

    def test_rotate_two_keys(self) -> None:
        pool = KeyPool(["a", "b"])
        assert pool.rotate() == "b"
        assert pool.current_index == 1
        assert not pool.is_exhausted

        assert pool.rotate() == "a"
        assert pool.current_index == 0
        assert pool.is_exhausted  # wrapped

    def test_rotate_three_keys(self) -> None:
        pool = KeyPool(["x", "y", "z"])
        assert pool.rotate() == "y"
        assert pool.rotate() == "z"
        assert pool.rotate() == "x"
        assert pool.is_exhausted

    def test_full_cycle_returns_to_start(self) -> None:
        keys = ["a", "b", "c", "d"]
        pool = KeyPool(keys)
        for _ in range(len(keys)):
            pool.rotate()
        assert pool.current_index == 0
        assert pool.is_exhausted


class TestKeyPoolReset:
    def test_reset_clears_exhaustion(self) -> None:
        pool = KeyPool(["a", "b"])
        pool.rotate()
        pool.rotate()  # exhausted
        assert pool.is_exhausted

        pool.reset()
        assert not pool.is_exhausted

    def test_reset_allows_continued_rotation(self) -> None:
        pool = KeyPool(["a", "b"])
        pool.rotate()
        pool.rotate()  # exhausted
        pool.reset()

        result = pool.rotate()
        assert result == "b"
        assert not pool.is_exhausted


class TestKeyPoolRepr:
    def test_repr(self) -> None:
        pool = KeyPool(["a", "b"])
        r = repr(pool)
        assert "KeyPool" in r
        assert "size=2" in r
        assert "index=0" in r
        assert "exhausted=False" in r
