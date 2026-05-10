# 评审：WP-1.1 美股行情适配器（commit ae3dec8）

**分支**：`wp-1.1-us-data`（HEAD = `ae3dec8 test(data): add end-to-end CLI fetch test + fix Py3.12 deprecation`）
**Reviewer**：Project 内评审对话（Claude Architect/Reviewer）
**轮次**：r2（增量评审 r1 → r2）
**评审基线**：r1 的 4 项修改要求

---

## 增量审查方法

r2 与 r1 的关系是"对四个 critical/significant/minor 偏离的针对性修复"，所以本轮按 r1 报告的偏离编号一对一核对，外加：

1. **反向死亡测试**：手工回退 r2 关键修复，确认 r2 新增测试真能红灯
2. **活体复现**：在 mock yfinance + 真 SQLite 环境跑 CLI 二次调用，确认 r1 critical bug 不复发
3. **跨实例 / 乱序缓存验证**：模拟两个 adapter 实例共享缓存
4. **新 bug 探测**：检查修复路径是否引入回归

---

## ✅ r1 偏离修复确认

### 偏离 1（critical）→ commit `6103ae6` ✅

**修复方案**（评估）：
- `src/data/cache.py:38-56` 新增 `_MODEL_REGISTRY` + `register_model()`，幂等注册同 class，对名称冲突（同名不同类）显式 `ValueError`
- `src/data/cache.py:82-89` `_decode` 遇 `__model__` 信封时调 `cls.model_validate()` 还原；未注册则保留 dict envelope（friendly fallback）
- `src/data/yfinance_adapter.py:40-41` 模块加载时显式 `register_model(Stock)` + `register_model(PriceBar)`
- `tests/data/test_cache.py:68-89` 把"返回 dict"的旧断言改为 `assert isinstance(second, Stock)`
- `tests/data/test_cache.py:91-110` 新增 `test_unregistered_model_falls_back_to_dict` 文档化 fallback 行为

**反向死亡测试**（关键）：

我手工在 `_decode` 中删除 `__model__` 处理分支，重跑 `test_fetch_end_to_end_writes_to_db_twice`：

```
FAILED tests/data/test_cli.py::test_fetch_end_to_end_writes_to_db_twice
> AttributeError: 'dict' object has no attribute 'code'
src/data/repository.py:114: AttributeError
```

恢复修复后，测试再次通过。**死亡测试是真死亡测试**——能精确捕获 r1 报告的 bug 模式。

**活体复现验证**：

```
Cache miss type: PriceBar / isinstance(PriceBar): True
Cache hit  type: PriceBar / isinstance(PriceBar): True   ← r1 这里是 dict
Equal: True
Cache hit b2[0].open: 100.0  Decimal                      ← Decimal 正确还原
Cache hit b2[0].date: 2024-01-02  date                    ← date 正确还原
Stock cache hit: Stock True
```

**额外亮点**：
- `register_model` 的幂等性正确（同 class 重注册无报错），冲突保护正确（同名不同类显式 raise）
- fallback 到 envelope dict 而非 raise，保护未注册的 caller 不至于无声崩；信号清晰（dict 形状一看便知）
- `Decimal` / `date` 在 Pydantic `model_validate` 链路上自动从 ISO 字符串/字符串还原（Pydantic v2 默认 `strict=False`），无需手动二次解码

### 偏离 2（significant）→ commit `fed4cd0` ✅

**修复方案**（评估）：
- `src/data/yfinance_adapter.py:50` 引入 `_BULK_CHUNK_SIZE = 25` 常量，并附 docstring 说明"chunk size selected because past 30 yfinance response shape gets unwieldy and at 50+ a single failed ticker corrupts the chunk"
- `src/data/yfinance_adapter.py:129-185` 新增 `fetch_price_bars_bulk(codes, start, end) -> dict[str, list[PriceBar]]`，按 chunk 切分，每个 chunk 单次 `_fetch_chunk_cached`
- `src/data/yfinance_adapter.py:157-185` `_fetch_chunk_cached` 用 `tuple(sorted(chunk))` 作为缓存 key 一部分——保证乱序调用命中同一缓存
- `src/data/yfinance_adapter.py:120-127` `fetch_price_bars` 退化为 thin wrapper，把单 ticker 路径与 bulk 统一
- `src/data/yfinance_adapter.py:228-245` `_download_history` 接收 `str | list[str]`，向 yfinance 透传
- `src/data/yfinance_adapter.py:318-359` 新增 `_normalise_history_bulk` 处理 MultiIndex 列（`(field, ticker)` 与 `(ticker, field)` 两种排布都处理）
- `src/data/cli.py:100` CLI 一次性调 `fetch_price_bars_bulk(tickers, start, end)`

**活体验证**（105-ticker universe）：

```
Universe: 105 tickers
Chunk size: 25
HTTP calls: 5
Expected (ceil(105/25)): 5
All universe codes covered: True
Each chunk size <= 25: True
HTTP reduction vs r1: 21.0x fewer requests
```

**额外亮点**：
- 跨 adapter 实例缓存共享：实例 A 写、实例 B 读 → 0 次新 HTTP（确认 cache key 不绑 `id(self)`）
- 乱序请求缓存命中：先 `['SPY','QQQ']` 后 `['QQQ','SPY']` → 共享同一缓存（sorted tuple key 起作用）
- partial failure 处理：单 ticker 在响应里缺失（delisted/typo）→ 该 ticker 映射到 `[]`，其余 ticker 正常返回（`tests/data/test_yfinance_adapter.py:288-309`）
- chunk size 边界守护：`test_bulk_chunk_size_constant_is_reasonable` 钉死 `5 <= _BULK_CHUNK_SIZE <= 50`（防止有人下次随手改成 100 或 1）

### 偏离 3 → commit `243fe03` ✅

**修复方案**：
- `src/data/cli.py:76-79` 改为：
  ```python
  settings = get_settings()
  rate_limit: float | None = settings.YFINANCE_RATE_LIMIT or None
  adapter = YFinanceAdapter(rate_limit_per_sec=rate_limit)
  ```

**测试验证**：
- `test_fetch_passes_rate_limit_from_settings` 用 `_CapturingAdapter` 子类捕获 `__init__` kwargs，断言 `rate_limit_per_sec == 5`
- `test_fetch_zero_rate_limit_disables_throttling` 验证 `0 → None` 语义（防止 `1.0 / 0` 的 `ZeroDivisionError`）

**额外亮点**：
- `0 or None` 是 Python 习语，简洁但 r2 在 `cli.py:77` 的注释把语义讲清楚了（"0/None disables throttling"），可读性合格
- `_respect_rate_limit` 自身也守护了 `<= 0` 分支（`yfinance_adapter.py:257`）——双保险

### 偏离 4 → commit `ae3dec8` ✅

**修复方案**：
- `ruff format src/data/repository.py` 已应用，单行 `_build_upsert(...)` 调用已合并
- 全仓 `ruff format --check src/ tests/ scripts/` → "41 files already formatted" ✅

### 偏离 5 → commit `ae3dec8` ✅

**修复方案**：
- `src/data/yfinance_adapter.py:25` 改为 `from datetime import UTC, date, datetime`
- `src/data/yfinance_adapter.py:372` 改为 `datetime.fromtimestamp(first_trade, tz=UTC).date()`

**验证**：pytest 输出无 DeprecationWarning（之前的 stderr 中相关行消失）

### 偏离 6 → commit `ae3dec8` ✅

**修复方案**：
- 新增 `tests/data/test_cli.py:130-221` `test_fetch_end_to_end_writes_to_db_twice`：
  - 缩 universe 到 3 ticker、mock yfinance HTTP 边界、注入测试 SQLite session
  - 跑两次 `cli.fetch('us', 30)`
  - 第一次：断言 `EXIT_OK`、DB 有 `bars > 0`、`stocks == 3`
  - 第二次：断言 `EXIT_OK`、HTTP 调用计数不增长（缓存命中）、DB 行数不变（idempotent upsert）
- 新增 `test_fetch_passes_rate_limit_from_settings` 和 `test_fetch_zero_rate_limit_disables_throttling`

**额外亮点**：
- 端到端测试确实暴露了 r1 #1 的真实使用场景（DB 写入时 `bar.code` 访问）
- 测试用 mock 而非真 yfinance，回归速度快、可靠
- 第二次运行额外断言 HTTP 计数不变，连缓存有效性也守住了

---

## ✅ 第一层~第四层四层检查结果

| 层 | 项 | 结果 |
|----|----|------|
| 第一层 契约一致性 | `src/contracts.py` 改动 | ✅ 0 行 |
| | `src/db/models.py` 改动 | ✅ 0 行 |
| | `src/db/migrations/` 改动 | ✅ 0 行 |
| | `docs/CONTRACTS.md` 自动重生成 | ✅ 与仓库版本零 diff |
| 第二层 架构边界 | `grep "import litellm\|from openai\|import anthropic" src/data/` | ✅ 无输出 |
| | Repository 边界（仅 src/db/ 知 ORM） | ✅ 守住 |
| | Currency 字段在 `Stock` 构造时正确填充 | ✅ Currency.USD |
| 第三层 原则遵守 | `Decimal(str(...))` 防漂移 | ✅ 保持 |
| | 模型版本写死 / 温度归零 / LLM 走 Gateway | N/A（本 WP 无 LLM 路径） |
| | API key / secret / token 不进 git | ✅ 无泄漏 |
| 第四层 可执行验证 | `pytest tests/` | ✅ 76 passed（64 + 12 新增） |
| | `ruff check src/ tests/ scripts/` | ✅ All checks passed |
| | `ruff format --check src/ tests/ scripts/` | ✅ 41 files already formatted |
| | `mypy src/` | ✅ 0 issues in 28 files |
| | `python scripts/verify_invariants.py` | ✅ All architectural invariants OK |
| | r1 关键 bug 反向死亡测试 | ✅ 回退修复后死亡测试红灯 |
| | bulk fetch 真生效（105 → 5 HTTP） | ✅ 21x HTTP 减少 |

---

## 🆕 新发现（非阻塞，建议项）

### 建议 1：r2 没改 `Makefile`，下游分支可能继续偷过 format check

- 我在 r1 报告里把 `Makefile lint` 加 `ruff format --check` 标为"Phase 0 cleanup，不在本 WP 范围"。r2 也确实没动它。
- 当前 `make check` 仍然只跑 `ruff check`，不跑 `ruff format --check`。WP-2.1 / 2.5 / 2.7 已合入 main，下次有人改了 ruff 配置或新加文件忘格式化，`make check` 仍会偷过。
- **行动建议**：在 r2 合入 main 之后，单独开一个 chore PR：
  ```makefile
  lint: ## Lint + type-check + format-check
      uv run ruff check src/ tests/ scripts/
      uv run ruff format --check src/ tests/ scripts/
      uv run mypy src/
  ```
  这一改不属于 WP-1.1 范围，但避免下游 WP 持续侥幸过门。可以挂到一个 `chore-cleanup-r1` 类的小分支，或者下个 WP 顺手带。

### 建议 2：`test_fetch_passes_rate_limit_from_settings` 用 `_CapturingAdapter` 子类，潜在 monkeypatch 顺序敏感

- 该测试通过 `monkeypatch.setattr(cli_mod, "YFinanceAdapter", _CapturingAdapter)` 注入。pytest 默认 function-scope 自动还原，本身没问题。
- 但 `_CapturingAdapter` 重写 `__init__` 时 `super().__init__(**kwargs)` 接收 `**kwargs: object`——mypy 用 `# type: ignore[arg-type]` 屏蔽了告警。这种屏蔽是合理的（动态参数透传），但留个标记给后续 review 留意。
- **行动建议**：本 WP 不改。如果 V0.7 实盘对接时需要更严格的 `Settings` 注入测试，再回头看是否抽个 `AdapterFactory` 协议会更干净。

### 建议 3：`fetch_universe()` 仍按单 ticker 拉 metadata（concurrency 8 → 4）

- yfinance 没有 bulk metadata 端点，所以这层保持 per-ticker 是合理的。r2 把 `meta_sem` 从 8 缩到 4 配合新的 rate limit 是周到的。
- **观察**：实际启动 prompt 没明确要求 metadata bulk，`fetch_universe` 也不被 `cli.fetch()` 调用——CLI 是直接调 `fetch_stock_metadata` 在 metadata 循环里。`fetch_universe` 现在是个未被消费的公开方法，留作 future use 倒也无妨。
- **行动建议**：本 WP 不改。如果到 V0.6+ `fetch_universe` 仍未被 caller 消费，可以在 V1.x 数据层重构时清理。

---

## 🏗 跨 WP 影响

- **CONTRACTS.md / INVARIANTS.md / architecture.md / wbs.md / version-plan.md**：均无更新需求
- **与 main 当前已合入分支的整合检查**：
  ```
  git log --oneline main..wp-1.1-us-data -- src/contracts.py src/db/    # 无输出
  ```
  WP-1.1 完全没碰共享基础设施，整合到 main 是 pure addition，零冲突风险
- **下游 WP 解锁**：
  - WP-2.3（趋势动量策略）：现可基于 `PriceBarRepository.get_range()` 读历史数据动工
  - WP-2.7（回测引擎）：`PointInTimeDataView` 实现可基于本 WP 的 repository
  - WP-1.5（数据存储与缓存）：`StockRepository` / `PriceBarRepository` 已建立 Repository 模式，缓存层可独立扩展
- **r2 不影响**已合入的 WP-2.1（factor lib）、WP-2.5（signal tools）、WP-2.7（backtest engine）三个分支——它们读的是 contracts，不依赖 data 层实现细节

---

## 决议

- [x] **PASS — 合并到 main**
- [ ] ITERATE

**合并步骤建议**：
1. 把本评审报告（`reviews/wp-1.1-r1.md` + `reviews/wp-1.1-r2.md`）落地到 `wp-1.1-us-data` 分支后，merge 到 main
2. **可选 chore PR**：建议 1 提到的 `Makefile` `ruff format --check` 加固
3. r2 合入后，V0.1 路径上数据层就绪，下一批可启动的并行 WP 是 **WP-1.5 简化版**（如果还没合）+ **WP-2.3 趋势动量策略**（依赖本 WP 的数据 + 已合入的 WP-2.1 factor lib）

**对 Implementer 的反馈**：
r2 的修复质量明显高于一般"按要求改完"的水准。亮点包括：
1. 反向防御（`register_model` 名冲突保护、`_BULK_CHUNK_SIZE` 边界守护、cross-instance 缓存共享）
2. 文档化 fallback 行为而非隐藏（`test_unregistered_model_falls_back_to_dict`）
3. 死亡测试设计精准（`test_fetch_end_to_end_writes_to_db_twice` 的两轮断言把缓存生效性、DB 行数、HTTP 计数都覆盖到了）
4. 把"批量响应里某个 ticker 缺失"作为合法路径处理而不是 panic

这种 r2 是后续 WP 评审的标杆。

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 2026-05-10 | r1 | 初次评审，ITERATE。一个 critical bug + 三个 significant + 两个 minor |
| 2026-05-10 | r2 | r1 全部 6 项偏离已修复并经反向死亡测试验证，PASS |
