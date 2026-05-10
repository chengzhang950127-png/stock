# 回测层局部不变量

**作用域**：仅限 `src/backtest/` 及消费回测产出的代码。本文件不替代项目级 `docs/INVARIANTS.md`，是其下属子集，处理回测引擎特有的工程约束。

**修订规则**：本文件改动需同步 `docs/architecture.md §10.5`，反过来亦然。

---

## 不变量 #B1：close vs adj_close 严格分离

详细语义见 `docs/architecture.md §10.5` 第 4 条。

**简表**：

| 用途 | 字段 | 理由 |
|------|------|------|
| 决策（entry / exit / SMA 突破 / 支撑压力） | `bar.close` | 点位时点真实性 |
| 收益归因（daily_return / cumulative_return / nav 序列） | `bar.adj_close` | 剔除分红/拆股噪音 |
| mark-to-market 持仓估值 | `bar.close` | 当前真实头寸价值 |
| 策略代码内部因子计算 | 由 factor_lib 函数 docstring 定义（已在 WP-2.1 落地，遵循同一原则） | 与回测层一致 |

**违反检查**：

- 任何混用必须在 PR 描述中说明理由，reviewer 必须显式确认
- `tests/backtest/test_close_used_for_decisions.py` 与 `test_adj_close_used_for_returns.py` 显式校验

---

## 不变量 #B2：ExecutionCostModel currency 一致性

`BacktestEngine.__init__` 必须校验：

```python
if cost_model.currency != account.currency:
    raise ValueError(
        f"cost_model currency {cost_model.currency} does not match "
        f"account currency {account.currency}"
    )
```

**写入约束**：

- 引擎产生的每一笔 `Trade` 必须满足 `trade.currency == account.currency == cost_model.currency`
- `trade.fee` 数值的币种 = `trade.currency`

**V0.1 实施范围**：

- 仅实现 `US_DEFAULT_COST = ExecutionCostModel(slippage_bps=5.0, fee_per_share=Decimal('0.005'), min_fee=Decimal('1.0'), currency=Currency.USD)`
- HK 的成本模型在 WP-1.2 / V0.2 引入，不在本 WP 范围

**校验命令**：

```bash
grep -n "cost_model.currency" src/backtest/engine.py
grep -n "raise.*currency" src/backtest/engine.py
```

期望：两条都有显式输出，证明 currency 校验路径存在。

---

## 不变量 #B3：决策时点 vs 执行时点严格分离

详细语义见 `docs/architecture.md §10.5` 第 1-3 条。

**实现要点**：

- `BacktestEngine.step(T)` 内部顺序：
  1. **先执行**前一个交易日（T-1）排队的 BUY/SELL 单，价格 = T 日 `bar.open` × (1 ± slippage_bps)
  2. 重建 `view = PointInTimeDataView(historical_data, T)`，传给策略
  3. 策略产出 T 日信号 + 退出决策
  4. 把这些动作排进**待执行队列**（在 T+1 步内执行）
  5. T 日 close 做 MTM，append PerformanceSnapshot

- 回测窗口最后一个**可执行**交易日 = `end_date - 1`。`end_date` 当天的信号没有 T+1 数据，引擎可丢弃这些信号或在 `BacktestResult` 中标注 unexecuted

**校准例外**：`src/backtest/_calibration_strategies.py` 内的 BuyAndHold 类策略允许 T 日 close 决策 + T 日 close 执行的简化（一次买入永不卖，无 look-ahead 风险）。这种简化必须在测试 docstring 显式声明。

---

## 不变量 #B4：position_size_pct 基数与同日交易顺序

详细语义见 `docs/architecture.md §10.5` 第 8-9 条。

**实现要点**：

- `Signal.position_size_pct` 的基数 = 信号生成时刻的 NAV（cash + 全部持仓 MTM）
- 现金不足时按比例缩减 BUY 的 shares，记录 partial fill，不抛错
- 同日多笔交易顺序：先 SELL（释放现金）→ 再 BUY（消费现金）
- BUY 之间排序键：`(-confidence, stock_code)`，保证确定性

**测试覆盖**：

- 同一组信号在不同 dict 遍历顺序下产生完全一致的交易序列（确定性）
- cash 不足按比例缩减后总投入 ≈ 可用 cash（误差仅来自手续费 / 最低费用）
- 同日 BUY/SELL 混合场景下，SELL 释放的现金正确进入后续 BUY 的可用池

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-10 | v1.0 | 初版，新建文件，含 B1-B4。配套 architecture.md v1.2 §10.5 与 docs/INVARIANTS.md v1.2 #8 |
