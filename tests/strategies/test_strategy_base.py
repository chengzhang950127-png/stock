"""Tests for :class:`StrategyBase` invariants.

Covers:

* Direct instantiation of the abstract class fails.
* Subclasses that omit any abstract method also fail to instantiate.
* ``__init_subclass__`` rejects subclasses without a valid ``name`` / ``type``.
* ``__repr__`` includes the class name, ``name`` and ``type``.
* ``serialize_state`` / ``load_state`` defaults round-trip empty state.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.contracts import (
    ExitAction,
    ExitDecision,
    Position,
    Signal,
    Stock,
    StrategyParameters,
    StrategyType,
)
from src.strategies.base import StrategyBase


class _GoodStrategy(StrategyBase):
    name = "Good"
    type = StrategyType.BUILT_IN
    parameters = StrategyParameters()

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        return universe

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        return []

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="NOOP")

    def get_score(self, stock: Stock, date: date) -> float:
        return 0.0


def test_abstract_base_cannot_be_instantiated():
    with pytest.raises(TypeError):
        StrategyBase()  # type: ignore[abstract]


def test_subclass_missing_abstract_method_cannot_instantiate():
    class HalfDone(StrategyBase):
        name = "Half"
        type = StrategyType.BUILT_IN
        parameters = StrategyParameters()

        def screen(self, universe: list[Stock], date: date) -> list[Stock]:
            return universe

        # missing generate_signals / exit_rules / get_score

    with pytest.raises(TypeError):
        HalfDone()  # type: ignore[abstract]


def test_concrete_subclass_instantiates():
    s = _GoodStrategy()
    assert s.name == "Good"
    assert s.type is StrategyType.BUILT_IN


def test_subclass_with_empty_name_rejected():
    with pytest.raises(TypeError, match="non-empty string"):

        class _EmptyName(StrategyBase):
            name = ""
            type = StrategyType.BUILT_IN
            parameters = StrategyParameters()

            def screen(self, universe, date):
                return universe

            def generate_signals(self, candidates, date):
                return []

            def exit_rules(self, position, date):
                return ExitDecision(action=ExitAction.HOLD, reason_code="X")

            def get_score(self, stock, date):
                return 0.0


def test_subclass_with_non_string_name_rejected():
    with pytest.raises(TypeError, match="non-empty string"):

        class _BadName(StrategyBase):
            name = 123  # type: ignore[assignment]
            type = StrategyType.BUILT_IN
            parameters = StrategyParameters()

            def screen(self, universe, date):
                return universe

            def generate_signals(self, candidates, date):
                return []

            def exit_rules(self, position, date):
                return ExitDecision(action=ExitAction.HOLD, reason_code="X")

            def get_score(self, stock, date):
                return 0.0


def test_subclass_with_wrong_type_rejected():
    with pytest.raises(TypeError, match="StrategyType enum"):

        class _BadType(StrategyBase):
            name = "Bad"
            type = "BUILT_IN"  # type: ignore[assignment]
            parameters = StrategyParameters()

            def screen(self, universe, date):
                return universe

            def generate_signals(self, candidates, date):
                return []

            def exit_rules(self, position, date):
                return ExitDecision(action=ExitAction.HOLD, reason_code="X")

            def get_score(self, stock, date):
                return 0.0


def test_intermediate_abstract_subclass_skips_validation():
    """A subclass that adds a new abstract method should not have to set
    ``name`` / ``type`` until it's concrete."""
    from abc import abstractmethod

    class IntermediateBase(StrategyBase):
        @abstractmethod
        def my_extra_hook(self) -> int: ...

    # No name/type set, but it's still abstract — must not raise.
    assert IntermediateBase.__abstractmethods__  # still abstract


def test_repr_format():
    r = repr(_GoodStrategy())
    assert "_GoodStrategy" in r
    assert "name='Good'" in r
    assert "type=BUILT_IN" in r


def test_serialize_state_default_empty():
    assert _GoodStrategy().serialize_state() == {}


def test_load_state_default_noop():
    s = _GoodStrategy()
    # No-op default must accept arbitrary dicts without raising.
    s.load_state({"any": "thing"})
    assert s.serialize_state() == {}


def test_serialize_load_round_trip_for_overrider():
    class _StatefulStrategy(_GoodStrategy):
        name = "Stateful"

        def __init__(self) -> None:
            self._counter = 0

        def serialize_state(self) -> dict[str, object]:
            return {"counter": self._counter}

        def load_state(self, state: dict[str, object]) -> None:
            self._counter = int(state["counter"])

    a = _StatefulStrategy()
    a._counter = 7
    b = _StatefulStrategy()
    b.load_state(a.serialize_state())
    assert b._counter == 7
