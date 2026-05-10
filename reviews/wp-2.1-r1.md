# 评审：WP-2.1 策略基类与因子库（commit 0459fab）

**分支**：`wp-2.1-factor-lib`
**Reviewer**：Project 内评审对话（Architect/Reviewer，由用户授权）
**轮次**：r1
**评审基线**：Phase 0 + Phase 0.5 已合入 main（`3bd9ba2`）

---

## ✅ 通过项

### 整体工程质量

- 4 个 commit 粒度清晰，message 准确（`5de1573` → `97b3819` → `1aed391` → `0459fab`），与 prompt 建议的 5 段粒度大致对应（合并了 momentum 与其他因子的两段，是合理的工程判断）
- 81 个 strategies 测试 + 整体 110 个测试全过，远超 prompt 给的 ≥30 要求
- `make verify`（不变量校验）、ruff check、ruff format、mypy 全绿
- 不引入 pandas / numpy / LLM 库（AST 静态扫描确认，符合 prompt 显式要求）
- 严守了纯函数原则——`src/strategies/` 全树没有 `random` / `time.time` / `datetime.now` / `date.today` / 全局可变状态（grep 确认）

### `src/strategies/base.py` 的扩展

- `__init_subclass__`（`base.py:77-108`）实现得相当严谨：手算未填充 abstract 方法集合（因为 `ABCMeta.__new__` 在 `__init_subclass__` 之后才设 `cls.__abstractmethods__`），跳过中间抽象类的校验。`tests/strategies/test_strategy_base.py:137` 显式覆盖了这一边界
- `__repr__`（`base.py:110-118`）格式严格匹配 prompt 给的 `<TrendMomentumStrategy name='...' type=BUILT_IN>`
- `serialize_state` / `load_state` 选择了 default 实现路径——这正是 prompt 中明示允许的"风险大就走 default"分支。`base.py:29-37` 的 module docstring 把 trade-off 写清楚了：大多数策略是 price/fundamental 数据的纯函数，没有需要持久化的滚动状态；强制每个子类实现是 busy work
- 抽象方法签名与 Phase 0 完全一致，没有偷偷扩展或缩减参数（INVARIANT #6 的契约不变）

### `src/strategies/factor_utils.py`

- 6 个工具函数全部以 `_` 前缀标记为非公开 API（`factor_utils.py:8-14` module docstring 明确说明），符合 prompt 要求
- `_align_to_date`（`factor_utils.py:25-35`）在因子函数入口就**无条件丢弃 `date > as_of` 的 bars**——这是 look-ahead bias 防护的第一道闸门，调用方传错也拦得住

### `src/strategies/factor_lib.py` 的因子覆盖

prompt 列的 11 项全部实现且签名匹配：

| 因子 | 文件位置 | 字段使用 | docstring 字段约定 | 验收 |
|------|----------|----------|------------------|------|
| `momentum` | `factor_lib.py:49-81` | `adj_close` | ✅ "Uses `PriceBar.adj_close`..." | ✅ |
| `momentum_12_1` | `factor_lib.py:84-98` | `adj_close` | ✅ 继承 `momentum` | ⚠️ 见偏离 1 |
| `momentum_6m` / `momentum_3m` | `factor_lib.py:101-114` | `adj_close` | ✅ "Trailing N-month..." | ✅ |
| `simple_moving_average` | `factor_lib.py:122-142` | `close` | ✅ "Uses `PriceBar.close` (not `adj_close`)..." | ✅ 含 `test_uses_close_not_adj_close` |
| `is_above_sma` | `factor_lib.py:145-165` | `close` | ✅ "...for both the spot price and the SMA so the comparison is apples-to-apples..." | ✅ |
| `price_to_high` | `factor_lib.py:168-194` | `close` | ✅ "Uses `PriceBar.close`" | ✅ |
| `atr` | `factor_lib.py:202-236` | raw `high`/`low`/`close` | ✅ "Uses raw `high` / `low` / `close` (form-style)..." | ✅ 含 `test_uses_raw_high_low_close` |
| `relative_strength` | `factor_lib.py:244-261` | `adj_close` | ✅ 继承 `momentum` | ✅ |
| `volume_breakout` | `factor_lib.py:269-311` | `volume` | ✅ | ✅ |
| `realized_volatility` | `factor_lib.py:319-357` | `adj_close` | ✅ "...log returns on `adj_close`" | ✅ 含 `test_uses_adj_close` |

**字段约定的双向验证**：`test_uses_close_not_adj_close`（`test_factor_lib.py:152-163`）和 `test_uses_adj_close`（`test_factor_lib.py:452-478`）通过构造 `close` 与 `adj_close` 故意分离的 bar 验证函数读取的是哪个字段——这是非常扎实的"行为而非实现"测试。

### Look-ahead bias 防护

- `_align_to_date` 内部丢弃所有 `b.date > as_of` 的 bars
- `test_lookahead_bars_are_dropped`（`test_factor_lib.py:83-89`）: 同一序列、同一 as_of，传入完整 bars 与传入显式截断 bars 必须给出相同结果
- `test_future_bars_dropped_for_momentum` / `test_future_bars_dropped_for_sma`（`test_factor_lib.py:486-507`）: 在 base bars 之后追加 999 元高价的"未来"bar，结果必须不变
- `test_unsorted_input_handled`（`test_factor_lib.py:510-520`）: 倒序输入与顺序输入结果一致

### 边界与异常

- 不足窗口统一返回 `None`（或 `volume_breakout` 的 `False`），不抛异常；专门的 `test_empty_inputs_safe_across_factors`（`test_factor_lib.py:523-533`）批量验证
- `test_zero_starting_price_returns_none`（`test_factor_lib.py:536-547`）: 起始价为 0 的脏数据返回 `None` 而非 `ZeroDivisionError`——这一防御在 `factor_lib.py:79` 和 `:191` 都做了
- 不合法参数（`lookback_days <= 0` / `window <= 0` / `period <= 0` / `recent_window <= 0` / `threshold <= 0` / `lookback_days <= 1` for vol）抛 `ValueError`——不静默吃错

### Decimal vs float 严格区分

- 价格相关：`simple_moving_average` 返回 `Decimal`（`test_returns_decimal` 确认），`atr` 返回 `Decimal`（`test_atr_deterministic_decimal` 确认）
- 无量纲统计：`momentum*` / `realized_volatility` / `relative_strength` / `price_to_high` 返回 `float`
- 这条切分线是回测可复现性的核心，不能模糊

### 确定性

- `tests/strategies/test_factor_lib_determinism.py` 的 11 个测试覆盖每个公开因子的"两次调用结果完全相等"
- `test_input_order_independent`（`test_factor_lib_determinism.py:125-138`）: 倒序输入也得相同结果——确认 `_align_to_date` 的 sort 之后没有引入次序依赖

---

## ⚠️ 偏离项

### 偏离 1（语义需澄清）：`momentum_12_1` 是 12 月动量带 1 月跳过，不是经典 11 月动量

- **位置**：`src/strategies/factor_lib.py:84-98`
- **现象**：当前实现 `momentum(bars, as_of, lookback_days=252, skip_recent_days=21)`，得到的是"从 t-13 月到 t-1 月、跨度 12 个月"的总收益。我手算样例（300 bar 线性涨 +0.1/天）输出 `0.2456`，对应的就是 P[-21] / P[-273] - 1
- **学术标准**：Jegadeesh-Titman (1993)、Asness "Value & Momentum Everywhere" (2013) 等文献中的"12-1 momentum"惯指**11 个月**收益，即 R[-12 月, -1 月] = P[-21] / P[-252] - 1。这里跨度差一个月
- **影响**：
  - 短期：因子值确实随趋势单调，回测结果方向不会反；但绝对数值会与学术参考偏 1 个月窗口
  - 长期：WP-2.3（趋势动量策略）若要复现学术研究里的 momentum decile spread，会发现自家因子比文献快 1 个月——相关系数依旧高，但分位数边界会偏移
- **澄清要求**：本项不强求修改，但需要 architect 拍板：
  - 选项 A：保留当前语义，在 `momentum_12_1` docstring 末尾加一行 `Note: this is a 12-month return ending 1 month ago (i.e., t-13 → t-1), not the academic 11-month convention t-12 → t-1.`，让 WP-2.3 的策略作者知道
  - 选项 B：改为 `momentum(bars, as_of, lookback_days=11*21, skip_recent_days=21)`，使其等于学术的 11-month return
- **倾向**：选 A。当前实现是"`lookback_days` + `skip_recent_days`"参数化 API 的自然结果，改为 B 会让函数名"12_1"与参数 `lookback_days=11*21` 不一致，反而误导。文档化清楚就够

### 偏离 2（信息项，不阻塞）：`_align_to_date` 每次调用都做完整 filter + sort

- **位置**：`src/strategies/factor_utils.py:25-35`
- **现象**：复杂度 O(n log n)，单只股票一次因子调用没问题；WP-2.7 回测引擎对 5 年 × 500 标的 × 4 策略 × 多因子重复调用时，可能成为热点
- **影响**：V0.1 单策略 + 单标的子集不会暴露。但回测引擎落地后若发现性能瓶颈，可能需要在 factor_utils 层加 `assume_sorted=True` 快速路径或换 `bisect` 的预排序入口
- **修改要求**：本 WP 不改。**记录到 WP-2.7 的优化候选清单**，在那边落地时一并评估
- **架构含义**：当前 API 形态没有阻断后续优化路径——`_align_to_date` 是私有函数，未来可以加一条新公开形参（`bars_sorted_ascending: bool = False`）让回测引擎走快速路径，旧调用者无感

### 偏离 3（架构层关注点，不属于本 WP 修改范围）：`PriceBar` 没有 OHLC 内部一致性校验

- **位置**：`src/contracts.py` 的 `PriceBar` 模型（Phase 0 已落地，未在本 WP 范围）
- **现象**：我在手动 spot-check 时构造了 `close=129` 但 `high=101` 的脏数据，`atr` 输出 30.15——纯粹反映了我自己构造数据违反了 `low ≤ open/close ≤ high` 的隐含约束。算法本身正确
- **影响**：如果 WP-1.1（美股数据适配器）写入了不一致 OHLC（数据源 bug、复权处理 bug），下游因子会静默给出错误信号，且无单元测试能拦截
- **修改要求**：本 WP **不动**。但建议在 architecture 层评估：是否在 `PriceBar` 上加一个 Pydantic `model_validator(mode="after")` 强制 `low <= open <= high` 与 `low <= close <= high`。这是新的架构决策，需要 architect 拍板后再开 WP（很轻量，可能纳入 WP-1.1 的契约扩展）
- **倾向**：建议加。理由：契约层强校验比 100 个下游测试都靠谱，且 PriceBar 不是热路径上动辄百万次构造的对象（数据入库时校验一次）

### 偏离 4（风格事项，不阻塞）：Decimal 与 int 直接比较

- **位置**：`src/strategies/factor_lib.py:79`（`if start_price <= 0`）、`:191`（`if high <= 0`）、`:308`（`if history_avg <= 0`）
- **现象**：`Decimal` 与 `int` 的比较 Python 内置支持，但项目其他地方倾向写 `Decimal(0)` 保持类型纯净
- **影响**：无功能影响，纯风格
- **修改要求**：可选。下次微调或下个 WP 顺手改即可，不为此单独发起新一轮迭代

---

## 🔧 修改要求（直接复制给 Claude Code）

```
本轮评审 PASS。仅一项 docstring 微调，可在合并前补一个 commit，也可以推到下一个 WP 顺手改：

1. src/strategies/factor_lib.py:84-98 的 momentum_12_1 docstring 末尾追加一段注释：

   ```
   Note: This is a 12-month total return ending 1 month ago — i.e., the
   window spans approximately t-13 months to t-1 month, a 12-month
   measurement period. This differs from the strict academic "11-1 momentum"
   convention (Jegadeesh-Titman 1993) which measures the 11-month return
   from t-12 to t-1. The downstream trend-momentum strategy (WP-2.3) should
   be aware of which convention this implementation uses.
   ```

   理由：避免 WP-2.3 实现者复现学术论文 decile spread 时困惑因子分布与文献不齐。
```

---

## 📋 可执行验证结果

```bash
# 所有命令在 wp-2.1-factor-lib commit 0459fab 上跑

pytest tests/strategies/ -v
# 81 passed in 0.28s

pytest tests/ -q
# 110 passed in 0.84s

python scripts/verify_invariants.py
# All architectural invariants OK.

ruff check src/strategies/ tests/strategies/
# All checks passed!

ruff format --check src/strategies/ tests/strategies/
# 9 files already formatted

mypy src/strategies/
# Success: no issues found in 4 source files
```

**手动 spot-check（300-bar 线性上涨样本）**：

```python
# 274-bar 边界（needed for momentum_12_1）刚好可算
momentum_12_1(bars[:274], as_of=...) = 0.252      # 12-month return on linear-up
momentum_12_1(bars[:273], as_of=...) = None       # 不足窗口

# 300-bar 完整样本
SMA(50)  = 127.45    # close = 100 + 251*0.1 ~ 125.2 那段的均值
SMA(200) = 119.95    # 早期更低段的均值
ATR(14)  = 2.0       # H-L 恒定 2，符合预期
RealVol(60d, ann)    # 极小，因为线性涨没有日波动
```

合理范围 ✅

**架构边界扫描**：

```bash
# 策略层零 LLM
ast-scan src/strategies/ for {litellm, openai, anthropic} → NONE

# 策略层零 pandas/numpy
ast-scan src/strategies/ for {pandas, numpy} → NONE

# 策略层零非确定性来源
grep src/strategies/ for {random, time.time, datetime.now, date.today} → NONE
```

---

## 🏗 跨 WP 影响

- **CONTRACTS.md 是否需要更新**：否。本 WP 没改 `src/contracts.py`，公开契约不变
- **INVARIANTS.md 是否需要更新**：否。INVARIANT #1 / #6 都在测试中显式校验，无新不变量
- **与并行 WP-1.1 / WP-2.5 / WP-2.7 的契约一致性**：
  - WP-2.5（信号生成工具）将基于 factor_lib 的输出生成买卖区间，依赖的 `PriceBar` / `Decimal` 类型一致 ✅
  - WP-2.7（回测引擎）将通过 `PointInTimeDataView` 调用因子函数，传入的 `bars` 必然是已过滤的；本 WP 的 `_align_to_date` 是第二道闸，不冲突 ✅
  - WP-1.1（美股数据）写入的 `PriceBar` 必须满足 OHLC 内部一致（见偏离 3）。当前合约层未强校验，是潜在风险，但本 WP 无可改之处
- **下游 WP-2.3（趋势动量策略）**：可基于本 WP 直接动工。注意偏离 1 的语义说明
- **下游 WP-2.2（价值反转策略）**：本 WP 未实现基本面因子（PE/PB/ROE/FCF Yield），WBS §WP-2.1 范围本就不含基本面（V0.2 才加）。WP-2.2 实现时可在 `factor_lib.py` 同文件追加，也可分到 `factor_lib_fundamental.py` —— 待 WP-2.2 启动时决定

---

## 决议

- [x] **PASS** — 合并到 main
- [ ] ITERATE

**合并前可选动作**：偏离 1 的 docstring 一行补丁（不强制；如不补，记录在本评审报告的"已知尾巴"里足够）。

**合并后建议**：
1. 把"`PriceBar` OHLC 内部一致性校验"作为新议题挂到 architecture.md 的 TODO 池里，与 WP-1.1 启动 prompt 一起拍板
2. 把"`_align_to_date` 性能优化"挂到 WP-2.7 的优化候选清单
3. 本 WP 完成后，V0.1 路径上仍待补的核心是：WP-2.3（趋势动量策略，依赖本 WP）+ WP-2.5（信号生成工具）+ WP-2.7（回测引擎）+ WP-2.8 简化版。WP-2.3 可以立即启动

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-10 | r1 | 初次评审，PASS |
