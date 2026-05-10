# 评审：WP-2.5 信号生成工具（commit a18d4f5）

**分支**：wp-2.5-signal-tools
**Reviewer**：Project 内评审对话
**轮次**：r2（最终）
**评审依据**：r1 评审报告 `reviews/wp-2.5-r1.md` + r1 修改要求

---

## 修复确认

r1 提出的两项偏离均已修复，无副作用。

### 偏离 1（CI 阻塞）：ruff format

- r2 commit `a18d4f5` 在 `tests/strategies/signal_tools/test_sizing.py` 把三处 `position_size_fixed_risk(...)` 多行调用收回单行（diff 行 73-74、80-81、87-88）
- `ruff format --check src/ tests/ scripts/` 输出 `39 files already formatted`，**CI 现在会绿**

### 偏离 2（doctest 期望值）：exit.py 三处 docstring

- `src/strategies/signal_tools/exit.py:48` `Decimal('164.5')` → `Decimal('164.50')` ✅
- `src/strategies/signal_tools/exit.py:100` `Decimal('185.5')` → `Decimal('185.50')` ✅
- `src/strategies/signal_tools/exit.py:128` `Decimal('169.5')` → `Decimal('169.50')` ✅

**Reviewer 自纠**：r1 报告里写"应改为 `Decimal('185.500')`"是错的。Implementer 自己手算确认是 `Decimal('185.50')` 并按真实输出对齐——这是正确做法。我把"用 `stop_loss_from_atr` 计算得到 `Decimal('164.50')` 再传给 `take_profit`"那条路径的输出（`185.500`，3 位尾零）和 doctest 里"直接传字面 `Decimal('164.5')`"那条路径的输出（`185.50`，2 位尾零）混到一起了。Implementer 没盲从评审建议，是健康行为，应赞许。

`pytest --doctest-modules src/strategies/signal_tools/` 现在 10/10 全过。

---

## 📋 r2 可执行验证结果

| 项 | 结果 |
|---|---|
| `pytest tests/ -q` | ✅ 86/86 |
| `pytest --doctest-modules src/strategies/signal_tools/ -q` | ✅ 10/10 |
| `ruff format --check src/ tests/ scripts/` | ✅ 39 files already formatted |
| `ruff check src/ tests/ scripts/` | ✅ All checks passed |
| `mypy src/` | ✅ no issues found in 27 source files |
| `python scripts/verify_invariants.py` | ✅ All architectural invariants OK |

r2 commit 仅触及 `src/strategies/signal_tools/exit.py` 与 `tests/strategies/signal_tools/test_sizing.py`，**无越界改动**（`git diff main..HEAD -- src/contracts.py src/db/ src/llm/ docs/` 输出为空）。

---

## 🏗 跨 WP 影响

- **WP-2.3（趋势动量策略）**：本 WP 合入 main 后立即解锁。`buy_range_from_atr` + `stop_loss_from_atr` + `take_profit_from_risk_reward` + `position_size_fixed_risk` 已可直接组装 `Signal` 实例
- **CONTRACTS.md / INVARIANTS.md**：无需更新

## 📝 移交给后续 WP 的待办事项

记录在此，方便接手者不必重读 r1：

1. **WP-2.8 启动 prompt 加显式 checklist**：`position_size_fixed_*` 返回 share count（`Decimal`），`position_size_kelly` 返回 fraction（`float`）。`SignalRepository` 把 share count 写入 `Signal.position_size_pct: float = Field(ge=0.0, le=1.0)` 时必须做 `share_count * entry_price / portfolio_value` 的换算。Pydantic 的 `le=1.0` 是兜底但不能依赖（极小账户 `0 < shares < 1` 会静默通过）
2. **Decimal 尾零（如 `185.50`）保留是有意为之**——精度信息对 WP-2.7 的滑点建模有用。前端展示需要时再在 contracts 边界统一 `quantize(Decimal('0.01'))`，**不要回头改 signal_tools**

---

## 决议

- [x] **PASS** — 合并到 main
- [ ] ITERATE

合并指令：

```bash
git checkout main
git merge --ff-only wp-2.5-signal-tools  # 4 个 feat commit + 1 个 chore commit, 都是线性历史
git push origin main
git branch -d wp-2.5-signal-tools
git push origin --delete wp-2.5-signal-tools
```

合并后 V0.1 路径上仍待补的 WP：
- **WP-2.3**（趋势动量策略）— 现在解锁，可立即启动
- **WP-1.1**（美股数据适配器）— 已并行进行中
- **WP-2.7**（回测引擎）— 已并行进行中
- WP-2.8 简化版（单账户持仓管理）— 等 WP-1.1 + WP-2.3 + WP-2.7 收尾后启动

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-10 | r1 | 首次评审，ITERATE（CI 阻塞 + doctest 不一致） |
| 2026-05-10 | r2 | 修复确认，PASS。Reviewer 自纠 r1 中 `185.500` 的笔误 |
