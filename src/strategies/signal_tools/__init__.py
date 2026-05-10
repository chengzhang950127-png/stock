"""Pure-math signal tools shared by every WP-2.x strategy.

Strategies import the helpers they need directly::

    from src.strategies.signal_tools import (
        buy_range_from_atr,
        stop_loss_from_atr,
        take_profit_from_risk_reward,
        position_size_fixed_risk,
    )
"""

from src.strategies.signal_tools.entry import (
    buy_range_from_atr,
    buy_range_from_pullback,
    buy_range_from_support,
)
from src.strategies.signal_tools.exit import (
    stop_loss_from_atr,
    stop_loss_from_pct,
    take_profit_from_risk_reward,
    trailing_stop,
)
from src.strategies.signal_tools.sizing import (
    position_size_fixed_pct,
    position_size_fixed_risk,
    position_size_kelly,
)

__all__ = [
    # entry
    "buy_range_from_atr",
    "buy_range_from_support",
    "buy_range_from_pullback",
    # exit
    "stop_loss_from_atr",
    "stop_loss_from_pct",
    "take_profit_from_risk_reward",
    "trailing_stop",
    # sizing
    "position_size_fixed_pct",
    "position_size_fixed_risk",
    "position_size_kelly",
]
