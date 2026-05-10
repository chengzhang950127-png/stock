# 评审：WP-2.7 V0.1 回测引擎（commit eb47ee5）r1

**分支**：`wp-2.7-backtest-engine`（已合并到 main 作为 commit `48008d4`）
**Reviewer**：Project 内评审对话（Architect/Reviewer，由用户授权）
**轮次**：r1
**评审基线**：v1.2 doc 补丁（main `120fc4e`）

---

## ✅ 通过项

### 工程基础

- 9 个 commit 粒度清晰；测试 112 全过；ruff / mypy / `make verify`（含 INVARIANT #8 + 全部 8 项）全绿
- 测试规模超 WBS 要求：83 个 backtest 单测（要求 ≥35）+ 整体 112（要求 ≥60）
- 模块布局符合 v1.2 §10.5 + WBS 列出的 7 个文件目录

### 契约一致 & 架构边界

- `BacktestEngine.__post_init__` 显式 `cost_model.currency != account.currency raise ValueError`（`engine.py:131-135`），完美执行 INVARIANT #B2
- `PointInTimeDataView.get_bars()` 内部强制过滤（`data_views.py:62-64`），`get_bar_on()` 在 `day > as_of` 时抛 `LookaheadBiasError`（`data_views.py:74-78`）—— INVARIANT #8 第一道闸到位
- `_calibration_strategies.py` 在策略层之外（INVARIANT #6 因 `verify_invariants.py` 跳过 `_*.py` 而豁免，`d011f51` commit 同步加上）—— `BuyAndHoldStrategy` 不污染 `src/strategies/`
- 回测层零 LLM、零 pandas（仅 numpy 用于 metrics），`make verify` 抓得住
- `walk_forward.py` 锁签名抛 `NotImplementedError`，符合 V0.5 留空

### T+1 执行时点机制（INVARIANT #B3）

- `step()` 内 5 阶段顺序严格按 §10.5 #1-3：先填 T-1 队列 → 建 view → 策略决策 → 排队下一日 → MTM（`engine.py:185-217`）
- `_execute_pending_buy/sell` 用 `bar.open` 作为意向价（`engine.py:251, 277`）
- T+1 timing 在 SPY 校准里**实际验证通过**：第一个 snapshot (2020-01-02) NAV=$100,000 全现金（BUY 信号已生成但未填），trade `executed_at=2020-01-03`（隔日开盘填）

### 同日多笔顺序（INVARIANT #B4）

- `_fill_pending_orders` 显式 `sells = [...]` 然后 `buys = sorted([...], key=lambda o: (-o.confidence, o.stock_code))`（`engine.py:228-232`）
- 现金不足时 `affordable_shares` 缩减循环不抛错（`engine.py:286-294`），与 §10.5 #8 "记录 partial fill 不抛错" 对齐

### 配套测试覆盖

- `test_no_lookahead.py` 构造 `LookaheadStrategy` 故意访问 `as_of+1` 数据，断言抛出 `LookaheadBiasError`，符合 INVARIANT #8 强制要求
- `test_close_used_for_decisions.py` + `test_adj_close_used_for_returns.py` 显式校验字段使用边界（INVARIANT #B1）
- `test_execution_timing.py` + `test_same_day_ordering.py` + `test_position_sizing.py` 覆盖 #B3 / #B4 全套场景

---

## ⛔ Blocker：`_compute_daily_return_adj` 数值上是错的

### 偏离 1（必修，阻塞 PASS）：`daily_return` 计算混用了两套 NAV 帧

- **位置**：`src/backtest/engine.py:518-543` `_compute_daily_return_adj()`
- **现象**（SPY 校准实测，输入是 close 涨 80%、adj_close 涨 96.5% 的 1304 天合成序列）：

  ```
  First 5 snapshots:
    2020-01-02  NAV=100000.00   daily_ret=+0.000000%
    2020-01-03  NAV= 99948.49   daily_ret=-8.232371%   ← 单日 -8.2%？
    2020-01-06  NAV= 99993.79   daily_ret=-8.137480%
    2020-01-07  NAV=100039.05   daily_ret=-8.131459%
    ...
  Last 3:
    2024-12-31  NAV=180229.93   daily_ret=+0.045288%

  daily_return stats: min=-8.23%  max=+0.05%  mean=-4.10%  std=2.37%
  Compounded daily returns: 0.0000  (= total return −100%)
  Sharpe (annualized): -27.61
  ```

- **根因**：`_compute_daily_return_adj` 的分母是 `self._snapshots[-1].nav`（昨日 close-based MTM），分子是 `cash + sum(shares * adj_close)`（今日 adj_close-based 估值）。两者**不在同一会计帧**：
  - 昨日 NAV 是 close-based（snapshot 当日的 raw close × shares）
  - 今日 "adj NAV" 用 adj_close（在历史日 < close，因为 adj_close 是后向调整）

  在 BUY 填仓的第一天（2020-01-03），昨日 NAV = $100,000（建仓前现金），而今日 adj NAV ≈ $0 + 307 × adj_close($165) ≈ $50,700，分子比分母低 ~50%。每天都是 -8% 左右的虚假"暴跌"。

- **影响**（按重要性递减）：
  1. **Sharpe / Sortino 数值彻底失真**：负的 -27.6 完全不能用作业绩评价。这是 V0.1 业绩对比的核心指标
  2. **WBS WP-2.7 验收的核心目标失守**：v1.2 改 ±2%。两个版本都假设 daily_return 序列在数学上正确——它现在不正确
  3. **下游 WP 全部受影响**：WP-2.3（趋势动量）、WP-2.6（自定义）、WP-3.4（助手胜率档案）都依赖 PerformanceSnapshot 的 daily_return 与 metrics 的 Sharpe/Sortino——它们目前会拿到不可信数据
  4. **测试套件没抓住**：`test_calibration_spy_buy_and_hold.py` 只断言 `total_return ∈ (0.95, 1.0)`、`max_drawdown ≈ 0.50`，**没断言 Sharpe / Sortino 应该是合理正值**——所以 83 个测试 + 112 个全过的事实下面盖住了一个数值 bug

- **修改要求**：

  ```
  请重写 _compute_daily_return_adj() 让分子分母在同一会计帧。两个可选方案：

  方案 A（推荐）：把 prior_nav 也换成 adj_close-based "shadow NAV"。
    - 引擎维护一个独立的 _prev_adj_nav: Decimal 状态变量
    - 每次 step 结尾在 _record_snapshot 里 update：
        self._prev_adj_nav = self._cash + sum(state.quantity * bar.adj_close for ...)
    - daily_return = (today_adj_nav - prev_adj_nav) / prev_adj_nav
    - prev_adj_nav 初值 = self._initial_nav（cash-only，无歧义）
    - PerformanceSnapshot.nav 保持 close-based（INVARIANT #B1 不变）
    - cumulative_return 同步切到 adj_nav 累积（语义自洽）

  方案 B：最小改动方案——daily_return 改用 close-based。
    - 直接 daily_return = (today_close_nav - prev_close_nav) / prev_close_nav
    - 失去 "TR with dividends" 语义；与 §10.5 #4 "收益归因用 adj_close" 直接冲突
    - 仅推荐为应急回退，不应是最终方案

  必加测试：
  1. tests/backtest/test_metrics.py 加 test_buy_and_hold_sharpe_is_positive_for_uptrend
     —— 1304 天 80% 上涨的合成序列，断言 Sharpe ∈ (3.0, 200) 而不是 -27
  2. tests/backtest/test_calibration_spy_buy_and_hold.py 加 test_compounded_daily_returns_match_total_return
     —— 用 close==adj_close 的合成序列（无分红）跑回测，断言
     prod(1 + daily_returns) ≈ 1 + total_return（误差 < 0.5%）

  这两个测试本应在 r1 把 bug 抓住，没抓住是测试设计盲点，必须补上。
  ```

### 偏离 2（必修，阻塞 PASS）：`metrics.total_return` 与 README "yfinance total return" 语义不齐

- **位置**：`src/backtest/metrics.py:226`（`tr = total_return_from_navs(navs)`）+ `README.md:181-188`
- **现象**：
  - `metrics.total_return` 用 `nav[-1]/nav[0] - 1`，nav 是 close-based MTM（INVARIANT #B1 第三行"MTM 使用 close"），所以 `metrics.total_return` 实际等于 close-based **价格回报**
  - 我合成 SPY 的 close 涨 80%、adj_close 涨 96.5%，引擎报 `total_return = 80.23%`——符合 close ratio
  - README 说 "must reproduce the yfinance-source **total return** within ±2%"。"Total return" 在金融里默认指带分红 TR——即 yfinance 的 Adj Close 比率（SPY 2020-2024 ≈ 96-97%）
  - 比对错框架会让 reviewer 看到 ~16% 缺口，误判为 bug
- **影响**：核心 acceptance gate 模糊；执行得不准
- **修改要求**：选一个改：
  - **方案 A**（架构清晰）：`PerformanceMetrics` 增加 `total_return_with_dividends: float`，从 compounded daily_return 算（前提是偏离 1 修好了）；保留 `total_return` 作为价格回报；CLI 输出两者
  - **方案 B**（README 改语义）：`README.md:181-188` 把 "yfinance-source total return" 改为 "yfinance Close-based price return (NOT Adj Close TR)"，明确比对的是价格序列。这是 V0.1 的诚实做法
  - 两条任选其一，但**架构层面需要在 `architecture.md §10.5` 注脚里补一句"V0.1 metrics.total_return 是价格回报，不是 TR；TR 的口径与 nav 序列因 §10.5 #5 约 dividend reinvestment 差额而分离"**

---

## ⚠️ 偏离项（修改但不阻塞）

### 偏离 3（重要，应在合并前补）：SPY 校准 acceptance gate 实际未跑

- **现象**：用户提交说 "112 tests pass / ruff / mypy / 8 invariants 全过"，但 **没附实际 SPY yfinance 比对数字**。WBS §WP-2.7 v1.2 明确写 "校准 acceptance gate（不可让步）...校准未通过不能 PASS"
- **`test_calibration_spy_buy_and_hold.py` 是合成 ramp 测试**，不是 yfinance 比对（其 docstring 自己说 "the companion reviewer-side acceptance gate ... runs against real SPY data via the CLI"）
- **README 把比对责任推给 reviewer**："Until then, the reviewer manually downloads from Yahoo Finance"——但 reviewer 也没跑（我的沙箱无法访问 yfinance / raw.githubusercontent.com / stooq，所有上游均被网关拒绝）
- **现实路径**：v1.2 加入这条 acceptance gate 时假设了 WP-1.1 数据适配器先于 WP-2.7 落地。当前实际是 WP-2.1 → WP-2.5 → WP-2.7 的顺序，WP-1.1 还在分支上未合并 → 当前**没有人**能完成这条 gate
- **修改要求**：

  ```
  请你（用户）在本地机上跑下面这串命令并把结果贴回：

  # 1. 拉 SPY（本地有 internet 能到 yfinance）
  uv pip install yfinance
  python -c "
  import yfinance as yf
  df = yf.download('SPY', start='2020-01-01', end='2025-01-01',
                   auto_adjust=False, progress=False)
  df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
  df.to_csv('/tmp/spy.csv')
  "

  # 2. 跑 CLI（修复偏离 1+2 之后）
  uv run python -m src.backtest.cli run \
      --strategy buy_and_hold --ticker SPY \
      --period 2020-01-01:2024-12-31 --calibration-mode \
      --csv /tmp/spy.csv --output /tmp/spy_bh.json

  # 3. 把 /tmp/spy_bh.json 贴回评审对话——我会与公开 SPY 5 年回报对照（±2%）
  ```

  完成 r2 时把这串数字附上。**没这串数字 PASS 不下来**——这是 WBS 明定的"不可让步"

### 偏离 4（信息项）：`metrics.calculate_metrics` 文档与实现轻微脱节

- **位置**：`src/backtest/metrics.py:202-210`（`calculate_metrics` docstring）
- **现象**：docstring 说 "consumes those values directly"（指 `snapshot.daily_return` / `snapshot.cumulative_return`）。但 `calculate_metrics` 实际上只读 `daily_returns = [s.daily_return for s in snapshots]` 和 `navs = [s.nav for s in snapshots]`，**完全没用 `snapshot.cumulative_return`**——它从 navs 重新算 total_return。这是个小的语义冗余
- **影响**：无功能 bug，但 `cumulative_return` 字段在 metrics 计算路径上被静默忽略，未来重构时容易踩雷
- **修改要求**：可选。要么 metrics 用 snapshots 里现成的 cumulative_return，要么 docstring 删掉对它的引用。下个 WP 顺手改

### 偏离 5（信息项）：`avg_cost_close` 加权平均 quantize 精度

- **位置**：`src/backtest/engine.py:332-337`（合并 BUY 时的加权平均）
- **现象**：`_PRICE_QUANTUM = Decimal("0.0001")` 仅 4 位精度，多次合并 BUY（例如 100 次小额加仓）会累积量化误差，影响 `avg_cost` 长期准确
- **影响**：V0.1 单次 BUY 的策略影响为零；V0.2+ 趋势动量频繁加仓时可能轻微偏差
- **修改要求**：本 WP 不动。挂到 WP-2.3 的优化候选清单

### 偏离 6（架构层关注，**升级到 Architect 决策**）：repo 的 `architecture.md` 与 Project knowledge file 已经发生 drift

- **位置**：`docs/architecture.md` v1.2 vs Project knowledge file `architecture.md` v1.1
- **现象**：repo 当前的 architecture.md 跳过 §10.4，第 4 章是"4.3 升级机制 / 4.4 仓位过渡 / 4.5 公平比较"。**Project knowledge file** 的 architecture.md 已经走到 v1.1，含 §4.3 影子账户初始资本 + §10.4 货币与资金记账，private 仓库注脚已删——这些**都没进 repo**
- **更糟**：repo 的 v1.2 §10.5 注脚明确写 "原 doc 在 §10.3 之后直接进入 §11，没有 §10.4。本次按 v1.2 patch 包整套交叉引用（§10.5 / #B1-B4）锁定的编号插入为 §10.5，§10.4 编号有意留空"——这与 Project file 中 §10.4 = Currency 的事实**直接冲突**
- **追溯**：repo 的 architecture.md 历史只有三个 commit：
  1. `f231b9f` (Phase 0 docs drop)
  2. `d6e25da` (private repo footnote)
  3. `46261e3` (v1.2 §10.5)

  也就是说 v1.1 架构补丁（§4.3 + §10.4 + 删 private 注脚）**从未被 commit 到 repo**。Phase 0.5 的代码 commit（`3490fe6`、`b573e6f`）确实加了 Currency 字段到 contracts 和 ORM——但驱动这次代码改动的"§10.4 货币与资金记账"架构条款本身没进 repo
- **影响**：
  - 后续 WP 评审依赖 architecture.md 校验"§10.4 强制要求 currency 字段"——repo 里查无此条
  - v1.2 §10.5 自己声称 "§10.4 编号有意留空"，但 Project file 已占用了 §10.4 = Currency。两套文档版本号将来会撞车
  - private 仓库注脚还在 §10.3，但用户当前实际是 public 仓库
- **修改要求**：在 r1 PASS 之前补一个 **v1.3 doc-only 补丁**：
  - 把 Project file 的 §4.3 影子账户初始资本规则同步进 repo（4.3-4.5 顺移）
  - 把 Project file 的 §10.4 货币与资金记账同步进 repo（删除 v1.2 §10.5 注脚里"§10.4 编号有意留空"那一句）
  - 删除 §10.3 末尾过时的 private 仓库注脚
  - 修订历史加一行 `2026-05-10 | v1.3 | doc-only sync: pull v1.1 §4.3 + §10.4 from project knowledge into repo; remove obsolete §10.4-blank note from §10.5 footer; strip private-repo footnote`

---

## 🔧 修改要求（直接复制给 Claude Code）

```
本轮评审 ITERATE。两个 blocker，一个补 acceptance gate：

【Blocker 1 — 必修】src/backtest/engine.py:518-543 的 _compute_daily_return_adj()
分子（adj_close-based today nav）和分母（close-based prior nav）不在同一帧。
SPY 校准实测：1304 天 80% 上涨的合成序列报出 Sharpe = -27.61，
min daily_return = -8.23%。

修法（推荐方案 A）：
1. 在 BacktestEngine 字段加一个 `_prev_adj_nav: Decimal`，__post_init__ 设为
   `self.account.cash`（因为初始全现金，adj_NAV = close_NAV = cash）
2. _compute_daily_return_adj 改为：
     today_adj_nav = self._cash + sum(state.quantity * bar.adj_close ...)
     daily_return = float((today_adj_nav - self._prev_adj_nav) / self._prev_adj_nav) if self._prev_adj_nav > 0 else 0.0
3. 在 _record_snapshot 里 update：self._prev_adj_nav = today_adj_nav（在
   计算完 daily_return 之后）
4. snapshot.cumulative_return 同步：考虑也切到 adj_nav 累积（架构问题，见 Blocker 2）

【新增测试 — 必加】
- tests/backtest/test_metrics.py 加 test_buy_and_hold_sharpe_positive_for_smooth_uptrend
  → 1304-bar 80% smooth uptrend，Sharpe ∈ (3.0, 200) 且 > 0
- tests/backtest/test_calibration_spy_buy_and_hold.py 加
  test_compounded_daily_returns_match_total_return
  → 当 close == adj_close（无分红场景）时，
    prod(1 + s.daily_return for s in snapshots) ≈ 1 + metrics.total_return
    误差 < 0.5%

【Blocker 2 — 必修】metrics.total_return vs README "yfinance total return" 语义统一

二选一：
方案 A：PerformanceMetrics 加 total_return_with_dividends 字段，从 compounded
  daily_return 算（前提：Blocker 1 修好）。CLI _serialize_result 把两个都输出。
方案 B：README.md:181-188 把 "yfinance-source total return" 改成
  "yfinance Close-based price return (NOT Adj Close TR)"，明确 V0.1 比对价格回报。

任何一种都需要在 docs/architecture.md §10.5 注脚补一句：
  "V0.1 metrics.total_return 等于 nav 序列两端比，是价格回报；
   带分红 TR 的口径见 metrics.total_return_with_dividends（方案 A）
   或留待 V0.7 实盘对接显式现金流（方案 B）。"

【SPY acceptance gate — 必跑】
修好 Blocker 1+2 后，在你（用户）本地机上跑：
  uv pip install yfinance
  python -c "import yfinance as yf; df = yf.download('SPY', start='2020-01-01', end='2025-01-01', auto_adjust=False, progress=False); df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]; df.to_csv('/tmp/spy.csv')"
  uv run python -m src.backtest.cli run --strategy buy_and_hold --ticker SPY \
    --period 2020-01-01:2024-12-31 --calibration-mode --csv /tmp/spy.csv --output /tmp/spy_bh.json

把 /tmp/spy_bh.json 完整贴回评审对话。

【偏离 6 升级到 Architect 决策】先于 r2 落 v1.3 doc-only 补丁，
把 project knowledge 中的 §4.3 + §10.4 同步进 repo，删 §10.3 私仓注脚 + §10.5
"§10.4 留空" 注脚。Architect 拍板后我提供 patch，由 Implementer 单 commit 落地。
```

---

## 📋 可执行验证结果

```bash
# 在 commit eb47ee5 上跑（Reviewer 沙箱，Python 3.12）

pytest tests/ -q
# 112 passed in 2.35s ✓

python scripts/verify_invariants.py
# All architectural invariants OK. ✓ (8 项含 #8 look-ahead)

ruff check src/backtest/ tests/backtest/
# All checks passed! ✓

mypy src/backtest/
# Success: no issues found in 8 source files ✓

# SPY 校准（合成 anchor 序列，close 涨 80%、adj_close 涨 96.5% / 1304 trading days）
python -m src.backtest.cli run --strategy buy_and_hold --ticker SPY \
    --period 2020-01-01:2024-12-31 --calibration-mode --csv /tmp/spy_synth.csv \
    --output /tmp/spy_bh.json

# 结果：
# Initial cash:       $100,000.00
# Final cash:         $0.01           ✓ (essentially fully invested)
# Final NAV:          $180,229.93     ✓ (close ratio = 80.23%)
# Total return:       80.2299%         ⚠ 与"TR" 命名语义不符（见 Blocker 2）
# Annual return:      12.5124%
# Sharpe:             -27.613         ⛔ 严重错误（见 Blocker 1）
# Sortino:            -13.737         ⛔ 同上
# Max drawdown:       0.0515%         ⚠ 合理（合成序列无回撤，仅当日 BUY 滑点）
# Calmar:             242.912         ⚠ 因 max_dd 极小而失真
# # trades:           1               ✓ (lump-sum)
# Total fees:         $1.54           ✓ (1 trade × max(min_fee, 0.005×307))
# # snapshots:        1304            ✓ (per trading day)
# # unexec signals:   0               ✓
# Trade detail:
#   direction=BUY, quantity=307.5176, price=$325.1796 (= open × 1.0005),
#   executed_at=2020-01-03 (T+1 of strategy fire on 2020-01-02)  ✓ T+1 timing OK

# Snapshot 头几条暴露 daily_return bug：
#   2020-01-02  NAV=$100,000.00  daily_ret=+0.000000%
#   2020-01-03  NAV= $99,948.49  daily_ret=-8.232371%   ← 应当 +0.04% 左右
#   2020-01-06  NAV= $99,993.79  daily_ret=-8.137480%
#   ...
#   1296/1304 days have negative daily_return  ← clearly broken
#   prod(1+daily_returns) = 0.0000  ← 复利下变 0 (-100% TR)
```

**架构边界扫描（手跑）**：

```bash
# 策略层零 LLM
grep -rnE "import litellm|from openai|import anthropic" src/strategies/ src/backtest/ → NONE ✓

# 策略层零 pandas（numpy 仅 backtest 用）
grep -rn "import pandas\|import pd" src/strategies/ src/backtest/ → NONE ✓

# 全量 LLM 调用走 Gateway
grep -rnE "import litellm|from openai|import anthropic" src/ --include="*.py" | grep -v "src/llm/" → NONE ✓

# Pending order 队列状态泄漏检查（手动看 engine.py:122 _pending_orders 重置时机）
# → run() 末尾 self._pending_orders.clear() ✓
```

---

## 🏗 跨 WP 影响

- **`CONTRACTS.md` 是否需要更新**：否（除非 Blocker 2 选方案 A 给 PerformanceMetrics 加新字段，那时需要重新 `make contracts`）。本 WP 现状没改 `src/contracts.py` 公开类型；`ExecutionCostModel` 在 `src/backtest/execution.py`，是回测层局部契约 ✓
- **`docs/INVARIANTS.md` 是否需要更新**：否。#8 已经在 v1.2 落地。Blocker 1 修好后**新增测试**会让 #8 + #B1 + #B3 + #B4 全套通过更稳，但条文不变
- **与并行/上游 WP 一致性**：
  - WP-2.1（factor_lib）：`PointInTimeDataView` + factor_lib `_align_to_date` 双闸不冲突
  - WP-2.5（信号工具）：本 WP 通过 `Signal` 契约消费，依赖 `position_size_pct`/`confidence` 字段——已是 ge=0/le=1 的 Pydantic 校验，无歧义
  - **Phase 0.5 Currency**：`account.currency`、`stock.currency`、`trade.currency` 全链路传递正确（`engine.py:472` `currency=self.account.currency` 写入 trade）✓
- **下游 WP-2.3（趋势动量策略）**：必须等 Blocker 1 修好后再启动。否则 WP-2.3 的回测结果会带着错的 Sharpe/Sortino，整个策略评估都不可信
- **下游 WP-2.8（持仓管理与 P&L）**：当前 `BacktestEngine` 内部已经 inline 了一份"账户状态机"（_PositionState + _cash + _trades），WP-2.8 启动时需要决定：是把这层提到 `portfolio/manager.py` 让 WP-2.7 反过来依赖，还是 WP-2.8 把当前 BacktestEngine 内部状态包装一层。这是 architect 拍板项，不属本 WP

---

## 决议

- [ ] PASS — 合并到 main
- [x] **ITERATE** — 期待第 r2 轮修复

**修复路径**：

1. 修 Blocker 1（daily_return 计算）+ 配套两个测试
2. 决定 Blocker 2（total_return TR 语义）方案 A 还是方案 B，落地 doc + 代码
3. 决定偏离 6（doc drift）是否在 r1 内同时落 v1.3 doc-only 补丁，还是 r2/r3 再做
4. 用户在本地用真 yfinance SPY 跑 acceptance gate，把 JSON 贴回 → Architect 对照公开 5y SPY 数字给 ±2% 容差判定
5. r2 期望产出：完整 `/tmp/spy_bh.json` + 修复 commits + 两个新增测试

**提醒（v2.0 红线检查）**：本轮所有问题都在 v1.x 范畴（契约/规格/数值正确性修订），**不涉及**架构铁律改动——AI 边界仍是 2 个调用点、LLM Gateway 中央化、Schema 强制、模型版本固定、温度归零五条不变。

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-10 | r1 | 初次评审，ITERATE。两个 blocker（daily_return 帧不齐 + total_return TR 语义）+ acceptance gate 未跑 + repo doc drift 升级 architect 决策 |
