# Architectural invariants

These seven invariants are the contract between every Work Package and the
rest of the system. Violating any of them is an automatic review fail. The
numbering and wording here is the canonical reference — `scripts/verify_invariants.py`
mirrors it 1-for-1, and CI runs that script on every PR.

---

## #1 — Decision path contains zero LLM calls

Stock screening, buy / sell pricing, regime classification, asset allocation,
and strategy promotion / demotion are all pure code rules. AI is permitted
in **exactly two** places:

1. News parsing inside the event-driven strategy
   (`src/strategies/event_driven.py` — file path per `wbs.md` WP-2.4)
2. Narrative generation inside the investment assistant
   (`src/assistant/narrative.py` — module called out in `version-plan.md` §V0.6)

Both wrap the LLM Gateway, never the underlying SDKs.

**Static check** (also implemented in `scripts/verify_invariants.py`):

```bash
grep -rn 'import litellm\|from openai\|import anthropic' \
  src/strategies/ src/portfolio/ src/assistant/ \
  | grep -v 'src/assistant/narrative.py' \
  | grep -v 'src/strategies/event_driven.py'
```

Expected: empty output.

---

## #2 — All LLM calls go through `LLMGateway`

Business code MUST NOT import `openai`, `anthropic`, or `litellm` directly.
Only modules under `src/llm/` may import them.

**Static check:**

```bash
grep -rn 'import litellm\|from openai\|import anthropic' src/ --include='*.py' | grep -v 'src/llm/'
```

Expected: empty output.

---

## #3 — Every LLM output is validated against a Pydantic schema

Every call to `LLMGateway.complete(...)` MUST pass `response_schema=`. The
gateway parses the model's output through that schema and raises
`LLMValidationError` if validation fails. There is no free-text variant on
purpose.

**Static check:**

```bash
grep -rn '\.complete(' src/ | grep -v 'response_schema'
```

Expected: empty output (the abstract method definition itself is whitelisted
by the verifier).

---

## #4 — Pinned dated model ids — no `latest` aliases

Every model id passed to the Gateway must include an unambiguous date suffix
(e.g. `claude-3-5-sonnet-20241022` or `gpt-4o-2024-08-06`). Aliases like
`claude-3-5-sonnet` (no date) drift silently as providers update them.

**Static check:**

```bash
grep -rn 'model="claude-3-5-sonnet"$\|model="gpt-4"$\|model="gpt-4o"$' src/
```

Expected: empty output. The Gateway also rejects un-dated ids at runtime
via `LLMGateway._validate_model_id`.

---

## #5 — `temperature=0.0` by default

LLM calls run at zero temperature unless an explicit, documented exception
exists. This is enforced inside `src/llm/`:

```bash
grep -rn 'temperature=' src/llm/ | grep -v 'temperature=0.0' | grep -v 'temperature=temperature'
```

Expected: empty output (the function-signature default `temperature: float = 0.0`
is allowed because it sets the floor).

---

## #6 — Every `Strategy` subclass implements all four abstract methods

`screen`, `generate_signals`, `exit_rules`, `get_score` are all `@abstractmethod`
on `StrategyBase`. The verifier walks `src/strategies/` and confirms each
concrete subclass overrides each method.

**Programmatic check** (run by `scripts/verify_invariants.py`):

```python
from src.strategies.base import StrategyBase
import importlib, pkgutil
import src.strategies as strategies_pkg

for _, name, _ in pkgutil.iter_modules(strategies_pkg.__path__):
    mod = importlib.import_module(f"src.strategies.{name}")
    for cls_name in dir(mod):
        cls = getattr(mod, cls_name)
        if isinstance(cls, type) and issubclass(cls, StrategyBase) and cls is not StrategyBase:
            for method in ("screen", "generate_signals", "exit_rules", "get_score"):
                assert getattr(cls, method) is not getattr(StrategyBase, method), (
                    f"{cls_name} did not override {method}"
                )
```

---

## #7 — Secrets, broker credentials, and personal positions never enter git

`.gitignore` blocks `.env*`, `*.pem`, `*.key`, `secrets/`, `credentials/`,
`user_data/`, `broker_credentials/`, `positions/`, and `trades/`. CI runs
two extra git-history checks beyond the local verifier:

```bash
git log --all -p | grep -iE "api[_-]?key|secret|password|token" | head -20
git ls-files | grep -E "\.env$"
```

Both are expected to be empty.

---

## #8 — Look-ahead bias 防护（v1.2 新增）

任何回测、历史模拟、信号回放代码访问历史数据必须经 `PointInTimeDataView` 包装。直接索引 `historical_data[code][i:]` 读 i+1 之后的 bar、或在策略代码里访问 `as_of` 之后的数据视为违规。

**强制要求**：

- 回测引擎 `BacktestEngine.step(current_date)` 必须每步重建 `PointInTimeDataView(historical_data, current_date)` 后再传给策略
- 策略代码不能直接持有 `historical_data` 全集引用，只能通过 `view.get_bars(code)` / `view.get_universe()` 访问
- `view.get_bars(code)` 内部必须用 `[b for b in all_bars[code] if b.date <= self.as_of]` **显式过滤**，不允许"约定调用方截断"
- 单元测试必须包含一个故意访问未来数据的假策略，断言抛出 `LookaheadBiasError`

**校验命令**：

```bash
# 策略代码不能直接访问 historical_data 全集
grep -rn "historical_data\[" src/strategies/ src/portfolio/ src/assistant/ 2>/dev/null

# 策略代码访问 bars 不能用裸切片读"未来"
grep -rnE "bars\[[^]]*:[^]]*\]" src/strategies/ 2>/dev/null
```

期望：第一条无任何输出（策略只通过 PointInTimeDataView 访问数据）；第二条无可疑切片（review 时人工确认负索引切片如 `bars[-N:]` 是合规的"取最近 N 日"，不是读未来）。

**作用域**：项目级。回测、paper trading、策略冻结校验、信号回放系统都受此约束。

**v1.2 之前的合规性回填**：WP-2.1 已实现的 `factor_lib._align_to_date` 是更严格的私有函数（在因子函数入口就丢弃 `bar.date > as_of` 的 bars），属于"第二道闸"，与 PointInTimeDataView 的"第一道闸"相互独立、不冲突。WP-2.1 因此对 #8 自然合规，无需追溯修改。

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 初始 | v1.0 | Phase 0 七条不变量定稿 |
| 2026-05-10 | v1.2 | WP-2.7 启动前补丁：新增不变量 #8「Look-ahead bias 防护」，作用域项目级，强制要求 PointInTimeDataView 显式过滤 + LookaheadBiasError 单测覆盖；同步 `docs/architecture.md §10.5` + `src/backtest/INVARIANTS.md` |
