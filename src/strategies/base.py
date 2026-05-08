"""
Strategy abstract base class.

Every concrete strategy (built-in and custom) MUST subclass :class:`StrategyBase`
and implement all four abstract methods. ``scripts/verify_invariants.py``
checks subclass completeness automatically (INVARIANT #6).

Important rules
---------------
* Strategy code MUST NOT import any LLM library directly (INVARIANT #1).
  All LLM use lives behind :class:`src.llm.gateway.LLMGateway`, and is
  permitted only inside the news-parsing helper of the event-driven strategy
  and inside the assistant narrative generator.
* Method signatures here are the contract — concrete subclasses cannot
  add or remove parameters. Use ``self.parameters`` for configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.contracts import (
    ExitDecision,
    Position,
    Signal,
    Stock,
    StrategyParameters,
    StrategyType,
)


class StrategyBase(ABC):
    """Common interface that the engine drives every strategy through.

    Daily call order (per market, per active strategy)::

        candidates = strategy.screen(universe, today)
        signals    = strategy.generate_signals(candidates, today)
        for position in open_positions:
            decision = strategy.exit_rules(position, today)

    ``get_score`` is consumed only by the custom blended strategy (V0.5+) and
    must still be implemented by every concrete strategy so the four-factor
    blender can call any of them uniformly.
    """

    name: str
    type: StrategyType
    parameters: StrategyParameters

    @abstractmethod
    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        """Filter the full tradeable universe down to this strategy's watch list.

        Parameters
        ----------
        universe:
            All instruments tradeable on the given date.
        date:
            Trading date being evaluated.

        Returns
        -------
        list[Stock]
            Subset of ``universe`` that the strategy considers.
        """

    @abstractmethod
    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        """Produce trade signals from already-screened candidates.

        Returns an empty list when the strategy has no convictions today.
        """

    @abstractmethod
    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        """Decide HOLD / REDUCE / EXIT for a single open position."""

    @abstractmethod
    def get_score(self, stock: Stock, date: date) -> float:
        """Score a single instrument from this strategy's perspective.

        Convention: ``0.0`` means "no conviction", ``1.0`` means "highest
        conviction". The custom blended strategy weighs these scores with
        the user's four-factor weights.
        """
