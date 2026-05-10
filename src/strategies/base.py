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

Subclass invariants
-------------------
``__init_subclass__`` enforces (only on concrete classes — those with no
remaining ``__abstractmethods__``):

* ``name`` must be defined as a non-empty ``str`` class attribute.
* ``type`` must be defined as a :class:`StrategyType` enum value.

We use ``__init_subclass__`` rather than a metaclass to keep ABC's metaclass
unchanged and avoid metaclass-conflict surprises for users who later mix this
with Pydantic models or other framework base classes.

State serialization
-------------------
``serialize_state`` / ``load_state`` are provided as **default implementations**
(empty dict / no-op) rather than abstract methods. Most strategies are pure
functions of price/fundamental data and have no carry-over state worth
persisting; forcing every subclass to implement them would be busy-work.
The V0.5 upgrade/downgrade flow only calls these on strategies that opt in
by overriding them.
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

    # ------------------------------------------------------------------
    # Subclass validation
    # ------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate ``name`` / ``type`` on every concrete strategy subclass.

        Skipped while a class still has unimplemented abstract methods so that
        intermediate abstract layers (e.g. a hypothetical ``MomentumStrategyBase``)
        don't have to declare placeholder ``name`` / ``type`` values.

        We compute the unfilled-abstract set manually because
        ``ABCMeta.__new__`` sets ``cls.__abstractmethods__`` only *after*
        ``__init_subclass__`` runs.
        """
        super().__init_subclass__(**kwargs)

        unfilled: set[str] = set()
        for klass in reversed(cls.__mro__):
            for attr_name, attr_val in vars(klass).items():
                if getattr(attr_val, "__isabstractmethod__", False):
                    unfilled.add(attr_name)
                elif attr_name in unfilled:
                    unfilled.discard(attr_name)
        if unfilled:
            return  # still abstract — concrete descendants will be checked

        name = cls.__dict__.get("name", getattr(cls, "name", None))
        if not isinstance(name, str) or not name.strip():
            raise TypeError(f"{cls.__name__}.name must be a non-empty string (got {name!r})")

        type_ = cls.__dict__.get("type", getattr(cls, "type", None))
        if not isinstance(type_, StrategyType):
            raise TypeError(
                f"{cls.__name__}.type must be a StrategyType enum value (got {type_!r})"
            )

    def __repr__(self) -> str:
        # ``name`` / ``type`` may be missing if a subclass forgets to set them;
        # __init_subclass__ catches that, but be defensive in case of partial
        # construction during testing.
        cls_name = type(self).__name__
        name = getattr(self, "name", "<unset>")
        type_ = getattr(self, "type", "<unset>")
        type_str = type_.name if isinstance(type_, StrategyType) else repr(type_)
        return f"<{cls_name} name={name!r} type={type_str}>"

    # ------------------------------------------------------------------
    # Required abstract interface
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Optional state serialization (V0.5 upgrade / downgrade)
    # ------------------------------------------------------------------

    def serialize_state(self) -> dict[str, object]:
        """Return any internal state worth persisting across versions.

        Default returns ``{}``. Override on strategies that maintain rolling
        windows, learned thresholds, or anything that would be expensive to
        rebuild from scratch on the next run.
        """
        return {}

    def load_state(self, state: dict[str, object]) -> None:
        """Restore state previously produced by :meth:`serialize_state`.

        Default is a no-op. Strategies that override :meth:`serialize_state`
        should also override this; the contract is round-trip equality
        modulo floating-point reproducibility.
        """
        return None
