# 评审：WP-1.1 美股行情适配器（commit 1c284b3）
**分支**：`wp-1.1-us-data`（HEAD = `1c284b3 docs(readme): record V0.1 US universe decision`）
**Reviewer**：Project 内评审对话（Claude Architect/Reviewer）
**轮次**：r1
**评审时间**：2026-05-10
---
## ✅ 通过项
- **契约一致性（第一层）**：未改动 `src/contracts.py` 与 `src/db/models.py`，`Stock` / `PriceBar` 模型签名零 drift；自动生成的 `CONTRACTS.md` 与仓库版本零 diff（`python scripts/generate_contracts_md.py | diff docs/CONTRACTS.md -` 干净）。
- **Currency 字段正确填充**：`src/data/yfinance_adapter.py:280` 和 `:245-253` 在 `Stock` / `PriceBar` 构造时显式传 `Currency.USD` / `Market.US`，与 Phase 0.5 的 §10.4 约束对齐。
- **架构边界（第二层）**：`grep -rn "import litellm\|from openai\|import anthropic" src/data/` 无任何输出；本 WP 完全是数据层，AI 边界与本 WP 无关，不变量 #1-#5 自动保持。
- **不变量校验**：`python scripts/verify_invariants.py` → "All architectural invariants OK."。
- **敏感信息**：`git ls-files | grep -E "\.env$"` 无输出；`git log --all -p | grep -iE "api[_-]?key|secret|password|token"` 仅命中文档/占位/`change-me-in-production`，无真实泄漏。
- **测试套件**：`pytest tests/ -v` → 64 passed（35 新增 + 29 已有），无回归。
- **静态检查**：`ruff check src/ tests/ scripts/` 通过；`mypy src/` 28 文件 0 issues。
- **Decimal 防漂移**：`_to_decimal` 走 `Decimal(str(value))`（`src/data/yfinance_adapter.py:53`），并有显式测试覆盖（`tests/data/test_yfinance_adapter.py:39-42`）。
- **Repository 边界**：仅 `src/data/repository.py` 知道 ORM，CLI / adapter 全程操作 Pydantic 契约（`src/data/repository.py:1-11` 文档说明也明确这一约定）。
- **跨方言 upsert**：`_build_upsert` 通过 `_upsert_dialect` 切换 PG / SQLite 的 `pg_insert` / `sqlite_insert`，repository 单元测试在 SQLite 内存库通过。
- **Universe 覆盖度**：`get_us_universe()` 返回 105 个 ticker，包含 SPY/QQQ/TLT/GLD/IWM + 100 大盘股，无重复（`tests/data/test_repository.py:124-138` 验证）。
- **`.gitignore`**：`.cache/` 已在 Phase 0 初始 commit 落定，本 WP 写入 `.cache/yfinance/` 自动被忽略，无脏 commit。
- **README 决策记录**：在 "Engineering decisions" 表末尾追加 V0.1 universe 选择条目（`README.md` 末尾），符合启动 prompt 的明确要求。
- **退出码契约**：`EXIT_OK=0` / `EXIT_NETWORK=2` / `EXIT_INTEGRITY=3`（`src/data/cli.py:39-41`），与 prompt 承诺的 cron / CI 集成约定一致，并有单元测试守护。
---
## ⚠️ 偏离项
### 偏离 1（**阻断 PASS**）：缓存命中返回 `dict` 而非 Pydantic 模型，二次运行 CLI 必崩
- **位置**：
  - `src/data/cache.py:50-61` — `_decode` 不识别 `__model__` 标记，对 Pydantic 模型只把外层 dict 透传回去
  - `src/data/yfinance_adapter.py:108-130` — `fetch_price_bars` 缓存命中时无 `model_validate` 还原
  - `src/data/yfinance_adapter.py:132-142` — `fetch_stock_metadata` 同样问题
  - `tests/data/test_cache.py:78-86` — 测试作者把"缓存命中返回 dict"当成"预期行为"写进了断言注释（"callers that need the typed model should `Stock.model_validate(cached_dict)` themselves"），但调用方（adapter / CLI）并未做这层校验
- **问题**：函数签名声明 `async def fetch_price_bars(...) -> list[PriceBar]`，但只在缓存 miss 时返回 `list[PriceBar]`；缓存 hit 时返回 `list[dict]`（每个 dict 形如 `{"__model__": "PriceBar", "data": {...}}`）。
- **活体复现**（在我容器里跑通了，关键节选）：
  ```
  Cache miss: type(bars1[0])=PriceBar
  Cache hit:  type(bars2[0])=dict
  --- First repository write (with bars1: actual PriceBar) ---
  OK
  --- Second repository write (with bars2: cached dicts) ---
  FAILED: AttributeError: 'dict' object has no attribute 'code'
  ```
  即：把 `cli.fetch` 在 24h 内运行第二次会直接 `AttributeError: 'dict' object has no attribute 'code'` 崩在 `PriceBarRepository.upsert_many` 的 `b.code` 行（`src/data/repository.py:113-124`）。`StockRepository._upsert_many` 同样会在 `s.code` / `s.currency.value` 处崩。
- **影响**：
  - **短期（V0.1 体验）**：用户每天跑一次 `python -m src.data.cli fetch` 是预期用法（注释里写死的 24h TTL 也表明这是设想节奏）。第一天成功，第二天起每天必崩，必须手动 `clear_cache()` 才能继续。这是个能让 V0.1 MVP 在第二天炸掉的硬伤。
  - **长期（下游 WP）**：任何依赖 `YFinanceAdapter` 的下游模块（WP-2.3 / 2.7 等）若直接调用 `fetch_price_bars` 而非走 DB 读取，都会踩同样的坑。
  - **测试盲点**：`test_fetch_price_bars_cached_skips_http` 只断言 HTTP 没被再次调用，没断言**返回值仍是 `list[PriceBar]`**。这是测试设计本身的缺陷——把 bug 误当 contract 入了测试。
- **修改要求**：见下方"修改要求 #1"。
### 偏离 2（必须修复或在 PR 描述里给出强理由）：批量拉取契约未兑现
- **位置**：
  - `src/data/yfinance_adapter.py:173-188` — `_download_history(code, start, end)` 只接受单 ticker
  - `src/data/yfinance_adapter.py:11-15` — 文件级 docstring 写明"Bulk fetches use `yf.download(tickers=[...])` to avoid one HTTP per ticker"
  - `src/data/yfinance_adapter.py:215-220` — `_normalise_history` 的 docstring 显式承认"this only handles the single-ticker shape"
- **问题**：启动 prompt "关键工程要求"第 2 条明文："**拉 100+ 只股票时不能每只单独 HTTP，要用 yfinance 的 download(tickers=[...]) 批量接口**"。当前实现 + CLI 编排（`src/data/cli.py:97` `asyncio.gather(*(one(t) for t in tickers))`）拉 105 ticker 的 universe 会发出 **105 次单独的 `yf.download`**，Semaphore 仅把并发限制到 8，本质仍是 N 次 HTTP。
- **活体证据**：
  ```
  Universe size: 105
  HTTP calls (yf.download invocations): 105
  One call per ticker?  True
  ```
- **影响**：
  - 短期：universe 全量拉一次的实际 HTTP 开销和 429 风险都被放大 ~10x；yfinance 在 2024-2025 年 throttle 越来越激进，单 IP 短时间发 100+ 请求很容易吃 401/429
  - 与偏离 3 叠加放大风险（rate limit 还没生效）
  - 不利于 V0.2 港股加进来后总量到 ~200 标的时的稳定性
- **修改要求**：见下方"修改要求 #2"。
### 偏离 3：配置的 `YFINANCE_RATE_LIMIT` 静默失效
- **位置**：
  - `.env.example:25` — `YFINANCE_RATE_LIMIT=2`
  - `src/config.py:45` — `YFINANCE_RATE_LIMIT: int = 2`
  - `src/data/cli.py:75` — `adapter = YFinanceAdapter()` 不传 `rate_limit_per_sec`
  - `src/data/yfinance_adapter.py:97-104, 199-208` — `_respect_rate_limit` 在 `self._rate_limit is None` 时直接 return
- **问题**：配置读了等于没读。生产环境每秒可发 N 个请求（Semaphore 8 唯一限制）。
- **影响**：与偏离 2 叠加，universe 全量拉一次会瞬时打 yfinance 8 路并发 + 105 总量。
- **修改要求**：见下方"修改要求 #3"。
### 偏离 4（小）：`src/data/repository.py` 格式有漂移
- **位置**：`src/data/repository.py:127-131`
- **问题**：`ruff format --check` 报需要重格式化（一处可单行写成多行的 `_build_upsert(...)` 调用）。`make check` 当前的 `lint` 目标只跑 `ruff check`、不跑 `ruff format --check`，所以这一处漂移没被门把。
- **影响**：纯外观，`make format` 一键修；但建议这一轮一并清理。
- **附带反馈给 Architect**：这是 Phase 0 `Makefile` 的 `lint` target 设计缺陷，建议下一轮 r2 或 Phase 0 cleanup 把 `ruff format --check` 加进 `lint`，避免后续 WP 持续偷过。
### 偏离 5（小）：`datetime.utcfromtimestamp` 在 Py3.12 触发 DeprecationWarning
- **位置**：`src/data/yfinance_adapter.py:274`
- **问题**：项目 `requires-python = ">=3.11,<3.13"`，Python 3.12 已 deprecate `datetime.utcfromtimestamp`，pytest 输出明确报警。
- **修复**：改为 `datetime.fromtimestamp(first_trade, tz=timezone.utc).date()`。
### 偏离 6：CLI orchestration 缺端到端测试，导致偏离 1 漏网
- **位置**：`tests/data/test_cli.py` 全文
- **问题**：CLI 测试只覆盖纯函数 `_validate_bars` 和退出码常量；`fetch()` / `check()` 的实际编排（adapter → repository 接驳）零覆盖。如果有一条"mock yfinance + 在内存 SQLite 上跑两次 `fetch()`、断言两次都成功且 DB 行数正确"的测试，偏离 1 当场会被发现。
- **修改要求**：见下方"修改要求 #4"。
---
## 🔧 修改要求（直接复制给 Claude Code）
```
请按下面顺序做以下修改，分四个 commit 推到 wp-1.1-us-data：
──────────────────────────────────────────────────────────────────
[修改 1] 修复缓存命中返回 dict 而非 Pydantic 模型（critical）
──────────────────────────────────────────────────────────────────
问题：当前 src/data/cache.py 把 Pydantic 模型存为
{"__model__": "<ClassName>", "data": {...}}，但 _decode 不还原。结果
缓存命中时返回的是 dict,下游调用 b.code / s.currency.value 直接 AttributeError。
二次跑 `python -m src.data.cli fetch --market us --period 1y` 必崩。
要求：
a) src/data/cache.py 的编码—解码层做对称化。最简单方案：
   - 维护一个 module-level 注册表 _MODEL_REGISTRY: dict[str, type[BaseModel]]
   - 提供 register_model(cls) 工具，业务侧在 import 时注册
   - _decode 在遇到 {"__model__": name, "data": payload} 时
     调用 _MODEL_REGISTRY[name].model_validate(payload) 还原成 Pydantic
   - 注册表里没有的就退化到当前行为（保留 dict 形态，不报错）
   或者次选方案：cached 装饰器接 return_type 参数（type[BaseModel]
   或 list[type[BaseModel]]），命中时显式 model_validate；adapter
   两个入口分别声明。
b) src/data/yfinance_adapter.py 中：
   - 在文件顶部 import 后调用 register_model(Stock); register_model(PriceBar)
   - 或者按次选方案，给两个 @cached 装饰器加 return_type 参数
c) tests/data/test_cache.py:
   - test_pydantic_model_round_trip 必须重写：第二次调用应得到的是
     真正的 Stock 实例，而不是带 __model__ 标记的 dict
     ```python
     fetched = fetch()
     cached_again = fetch()
     assert isinstance(cached_again, Stock)
     assert cached_again == fetched
     ```
   - 删除原注释里"callers that need the typed model should
     model_validate themselves"那段，因为新行为不需要调用方做这事
d) tests/data/test_yfinance_adapter.py:
   - test_fetch_price_bars_cached_skips_http 增加断言：
     ```python
     bars2 = await adapter.fetch_price_bars(...)
     assert all(isinstance(b, PriceBar) for b in bars2)
     assert bars1 == bars2  # 内容一致
     ```
commit message: fix(data): cache hit returns Pydantic models, not raw dicts
──────────────────────────────────────────────────────────────────
[修改 2] 用 yfinance 批量下载替换单 ticker 循环
──────────────────────────────────────────────────────────────────
问题：启动 prompt 明文要求 "拉 100+ 只股票时不能每只单独 HTTP，
要用 yfinance 的 download(tickers=[...]) 批量接口"。当前实现 105
ticker 拉一次 universe 会发 105 次单独 HTTP。
要求：
a) src/data/yfinance_adapter.py 新增方法：
   async def fetch_price_bars_bulk(
       self,
       codes: list[str],
       start: date,
       end: date,
   ) -> dict[str, list[PriceBar]]:
       """Bulk fetch. Internally batches `codes` in chunks of N=25 to keep
       individual responses parseable; calls yf.download(tickers=[...])
       once per chunk. Returns mapping of code -> list[PriceBar].
       Failed tickers map to []."""
   - 复用 _retry_async + 缓存：缓存 key 取 (sorted_codes_chunk, start, end)
   - _normalise_history_bulk(codes, df) 处理 yfinance 多 ticker 返回的
     双层 column index（field × ticker），逐 ticker 拆出来
   - 单 ticker 路径 fetch_price_bars 保留作为 thin wrapper:
     `return (await self.fetch_price_bars_bulk([code], start, end))[code]`
b) src/data/cli.py 的 fetch() 改为：
   - 不再用 asyncio.gather 一个个调
   - 把 universe 切成 chunk(size=25)
   - 每个 chunk 一次 fetch_price_bars_bulk
   - 仍保留 metadata 的并发拉取（yfinance 没有 bulk metadata 接口，
     这部分维持现状，但 sem 缩到 4 配合 rate limit）
c) 新增测试 tests/data/test_yfinance_adapter.py:
   - test_fetch_price_bars_bulk_one_chunk: mock yf.download 返回多 ticker
     DataFrame，断言三个 ticker 都被正确归一化
   - test_fetch_price_bars_bulk_chunks: 给 60 个 ticker，断言被切成
     至少 3 个 chunk，每个 chunk 调用一次 _download_history
   - test_fetch_price_bars_bulk_partial_failure: 一个 ticker 在响应里
     缺失，其余正常返回，缺失的那个映射到 []
d) src/data/yfinance_adapter.py 文件级 docstring 第 11-15 行已经
   宣称用了 bulk，本次修改让它真兑现。
commit message: feat(data): implement true bulk fetch via yf.download(tickers=[...])
──────────────────────────────────────────────────────────────────
[修改 3] 把 YFINANCE_RATE_LIMIT 真正接进来
──────────────────────────────────────────────────────────────────
问题：src/config.py 读了 YFINANCE_RATE_LIMIT=2，但 CLI 不把它
传给 adapter，rate_limit_per_sec 永远是 None。
要求：
a) src/data/cli.py:
   from src.config import get_settings
   settings = get_settings()
   adapter = YFinanceAdapter(rate_limit_per_sec=settings.YFINANCE_RATE_LIMIT or None)
b) tests/data/test_cli.py 加测试：
   def test_fetch_passes_rate_limit_from_settings(monkeypatch, ...):
       # mock get_settings 返回 YFINANCE_RATE_LIMIT=5
       # 调 fetch()，断言 adapter._rate_limit == 5
commit message: fix(data): wire YFINANCE_RATE_LIMIT into the CLI fetcher
──────────────────────────────────────────────────────────────────
[修改 4] CLI fetch 端到端测试 + 修复 Py3.12 deprecation + 一处格式
──────────────────────────────────────────────────────────────────
a) 新增 tests/data/test_cli.py 端到端测试（用 mock yfinance + 内存 SQLite）：
   def test_fetch_end_to_end_writes_to_db(monkeypatch, db_session, cache_dir):
       # mock _download_history 和 _fetch_info
       # mock get_us_universe 缩成 ('SPY', 'QQQ', 'AAPL')
       # 第一次调 fetch('us', period_days=10) → 断言 EXIT_OK
       # 查 PriceBarRepository.count(US) > 0
       # 第二次调 fetch('us', period_days=10) → 断言 EXIT_OK（不再崩！）
       # 查 PriceBarRepository.count(US) 仍正常
   这个测试是修改 1 的关键回归门，必须加。
b) 修复 src/data/yfinance_adapter.py:274 的 deprecation：
   - 把 `datetime.utcfromtimestamp(first_trade)` 改为
     `datetime.fromtimestamp(first_trade, tz=timezone.utc).replace(tzinfo=None)`
     再 `.date()`，或者直接用 datetime 库的 `date.fromtimestamp(first_trade)` 配合
     时区注释
c) 跑一次 `ruff format src/data/repository.py`，把
   src/data/repository.py:127-131 那处合并成一行的 _build_upsert 调用清掉。
d) 顺便建议 Phase 0 cleanup（不在本 WP 范围、单独 PR 做）：
   Makefile 的 lint target 加一行 `uv run ruff format --check src/ tests/ scripts/`，
   防止格式漂移。本 WP 不必做这个。
commit message: test(data): add end-to-end CLI fetch test + fix Py3.12 deprecation
──────────────────────────────────────────────────────────────────
[完成后自我验证 — 执行通过再 push]
──────────────────────────────────────────────────────────────────
uv run pytest tests/ -v          # 应是 64 + 4-6 个新测试全过
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/
uv run python scripts/verify_invariants.py
```
---
## 📋 可执行验证结果（评审者实跑）
| 项 | 结果 | 备注 |
|---|---|---|
| `pytest tests/data/ -v` | ✅ 35/35 pass | 但其中 `test_pydantic_model_round_trip` 把 bug 当成预期，见偏离 1 |
| `pytest tests/ -v` | ✅ 64/64 pass | 无回归 |
| `python scripts/verify_invariants.py` | ✅ All OK | 不变量 #1-#7 全通过 |
| `ruff check src/ tests/ scripts/` | ✅ All checks passed | |
| `ruff format --check src/ tests/ scripts/` | ⚠️ 1 file | `src/data/repository.py:127-131` 需 reformat（偏离 4） |
| `mypy src/` | ✅ Success: no issues found in 28 source files | |
| 真跑 `python -m src.data.cli fetch --market us --period 1y` | ⚠️ 沙箱无法访问 yfinance.com（403），但**第二次调用必崩**已通过 mock 复现确认（见偏离 1）|
| 抽样验证 SPY 2024-01-02 数据 | ⏸ 沙箱限制无法跑真实 yfinance；评审者本地建议在合 r2 后跑一次 |
| `git log --all -p \| grep -iE "api[_-]?key\|secret\|password\|token"` | ✅ 仅占位/文档 | 无真实泄漏 |
| `git ls-files \| grep -E "\.env$"` | ✅ 无输出 | |
| Currency 字段在 Stock 构造时正确填充 | ✅ Currency.USD | `_normalise_metadata` 测试覆盖 |
---
## 🏗 跨 WP 影响
- **与 `wp-2.1-factor-lib` / `wp-2.5-signal-tools` / `wp-2.7-backtest-engine`（已有远程分支）的整合冲突风险**：低。本 WP 只动 `src/data/`，不与上述分支共享文件。后续整合时建议跑 `git diff wp-1.1-us-data wp-2.7-backtest-engine -- src/contracts.py` 确认两边都没改契约。
- **是否需要更新 `docs/CONTRACTS.md`**：否（生成结果零 diff）。
- **是否需要更新 `docs/architecture.md` / `wbs.md` / `version-plan.md`**：否（本 WP 完全在 V0.1 数据层范围内，不触及架构原则或版本规划）。
- **是否影响下游 WP**：
  - WP-2.3（趋势动量）会调 `PriceBarRepository.get_range()` 读 DB，**不会**直接踩偏离 1 的缓存 bug —— **前提是数据成功写进 DB**。一旦偏离 1 让第二天的 `fetch` 崩掉，DB 数据陈旧后下游回测就是假数据。
  - WP-2.7（回测引擎）的 `PointInTimeDataView` 也是从 DB 读，同样依赖 `cli fetch` 持续可用。
  - 综上：**偏离 1 不只是单 WP 的瑕疵，是整个 V0.1 数据流水的健康前提**。必须修。
---
## 决议
- [ ] PASS
- [x] **ITERATE — 期待 r2 修复偏离 1（critical）+ 偏离 2-6**
**期望 r2 时间盒**：1 个 Claude Code 会话（约 2-3 小时），4 个 commit。完成后再次 push 到 `wp-1.1-us-data`，通知评审。
**r2 评审重点**：
1. 跑 `python -c "..."`，验证 `fetch_price_bars` 在缓存 hit 路径下返回 `list[PriceBar]`
2. 跑新增的 `test_fetch_end_to_end_writes_to_db` 测试两次连续运行不崩
3. 数一下 `_download_history` 的 mock 调用次数 vs universe size，验证批量真生效
4. 抽查 `adapter._rate_limit` 是否承接了 settings 值
