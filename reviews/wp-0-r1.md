# 评审：WP-0 Phase 0 基础脚手架（commit 37984c9）

**分支**：`main`（直接评审 main，因为 Phase 0 由 Implementer 直接合入）
**Reviewer**：Project 内评审对话（Architect + Reviewer 角色）
**轮次**：r1（首轮评审）
**评审时间**：2026-05-08
**仓库**：https://github.com/chengzhang950127-png/stock

---

## 概述

Phase 0 整体质量高于预期。所有四层检查（契约 / 边界 / 原则 / 可执行）通过，七条架构不变量全部静态 + 运行时双重验证清白，26 个测试全过，CI / lint / mypy / format 全绿。结构性偏离仅一处（与 WBS 旧版的 `Decimal` vs `float` 不一致），且实现侧选择正确——属于"实现先行倒逼文档对齐"的健康偏离。

**决议：PASS — 直接进入下一批 WP，无需 r2 迭代。**

---

## ✅ 通过项

### 第一层：契约一致性

- **`src/contracts.py:75-307`** — 所有 19 个 Pydantic 模型与 `phase0-claude-code-prompt.md` v1.2 规格一一对应。`ExitAction` / `ExitDecision` / `StrategyParameters` / `CustomBlendParameters` 全部就位，命名、字段、类型完全匹配
- **`tests/test_contracts.py:1-267`** — 16 个 round-trip 测试覆盖所有领域模型，全过
- **`docs/CONTRACTS.md`** — 由 `scripts/generate_contracts_md.py` 自动生成，与 `src/contracts.py` 当前状态零 diff（`diff /tmp/regenerated_contracts.md docs/CONTRACTS.md` 返回空）
- **`src/db/models.py:55-237`** — 10 个 ORM 表与 Pydantic contracts 在字段、命名、类型上对齐；用 `money_col` helper 统一了 `Numeric(20, 6)` 货币列
- **`src/db/migrations/versions/0001_initial_schema.py`** — Alembic 初始迁移覆盖全部 ORM 表，方言分支处理 Postgres 枚举 vs SQLite VARCHAR + CHECK，迁移在 SQLite 内存库上验证通过

### 第二层：架构边界

- **`src/llm/gateway.py:38-104`** — `LLMGateway` 抽象类签名匹配 architecture.md §3.3。强制 `response_schema` keyword-only 参数（缺失则编译期不能调用），强制 `temperature: float = 0.0` 作为默认。`_validate_model_id` 在运行时拒绝 `latest` 别名——**这是超出规格的额外防御**（规格只要求静态 grep）
- **`src/llm/mock.py:51-93`** — Mock 实现保留所有 Gateway-level invariants（仍然校验模型 id、仍然记录审计），FIXTURES + introspection-fallback 双轨保证测试既能精确控制又能默认通过
- **`src/llm/audit.py:34-66`** — In-memory ring buffer（容量 1000），记录 provider / model / temperature / schema name / prompt preview。Phase 0 acceptable，README:137 已自我披露持久化推迟到 WP-1.x
- **`scripts/verify_invariants.py:54-253`** — 七条不变量逐条静态化，与 `docs/INVARIANTS.md` 1:1 编号对应。AST-light 的 `.complete()` 调用扫描（不只是行级 grep）能正确处理多行调用和括号嵌套
- **`scripts/verify_invariants.py:71-74` whitelist** — 显式只放过 `src/assistant/narrative.py` 和 `src/strategies/event_driven.py`，路径与 architecture.md §3.1 + wbs.md WP-2.4 + version-plan.md §V0.6 严格对齐

### 第三层：原则遵守

- **模型版本写死**：`src/llm/gateway.py:51` 默认值 `claude-3-5-sonnet-20241022`；`src/config.py:39` 配置默认值同样带日期；`src/llm/gateway.py:100` 正则 `\d{8}|\d{4}-\d{2}-\d{2}` 兜底拒绝无日期 id（运行时 + CI 双重保险）
- **温度归零**：`src/llm/gateway.py:52` + `src/llm/mock.py:60` + `src/config.py:41` 三处默认值都是 `0.0`；`scripts/verify_invariants.py:161-185` 正则扫描 `src/llm/` 下任何非零温度赋值（排除签名默认 + pass-through）
- **审计日志**：每次 Mock 调用强制 `record_call`（`src/llm/mock.py:72-79`），`tests/test_llm_gateway.py:53-59` 验证审计被触发
- **降级路径**：`LLMValidationError` 和 `LLMServiceError` 区分语义错误 vs 服务错误（`src/llm/gateway.py:30-35`），Mock 在 schema 解析失败时主动抛出而非沉默返回（`src/llm/mock.py:88-93`）——故意 fail loud

### 第四层：可执行验证

```
$ pytest tests/ -v
====== 26 passed in 1.77s ======

$ ruff check src/ tests/ scripts/
All checks passed!

$ ruff format --check src/ tests/ scripts/
30 files already formatted

$ mypy src/
Success: no issues found in 23 source files

$ python scripts/verify_invariants.py
All architectural invariants OK.

$ alembic upgrade head    # against SQLite in-memory
INFO  Running upgrade  -> 0001, initial schema    # 干净通过

$ git log --all -p | grep -iE "api[_-]?key|secret|password|token"
# 仅 .env.example 占位、文档引用、JWT_SECRET="change-me-in-production" 占位
# 无真实 secret 泄漏

$ git ls-files | grep -E "\.env$"
# 无输出 —— .env 正确未被追踪
```

GitHub Actions `.github/workflows/ci.yml` 与本地 `make check` 流程对齐：lint → format check → mypy → verify_invariants → alembic migrate → pytest with coverage。Postgres service container 在 CI 内启动，覆盖了真正的 Postgres 枚举路径（不只是 SQLite fallback）。

### 加分项（超出规格的好工程）

- **`src/llm/gateway.py:86-104`** — 运行时模型 id 正则校验。规格只要求静态 grep（不变量 #4），实现额外加了 runtime guard。Defense in depth
- **`src/db/migrations/versions/0001_initial_schema.py:11-29`** — Migration 顶部 docstring 解释了 Postgres 枚举的两个坑（`sa.Enum` 不接受 `create_type=False`、`_on_table_create` 事件钩子重复触发 `CREATE TYPE`），并说明 dialect-branch 解决方案。结合 commit 历史 `22ba707` → `37984c9` 看，Implementer 真的踩坑→修复→落到 docstring，是诚实的工程日志
- **`src/utils/logging.py:19-50`** — `configure_logging` 用 `_configured` 哨兵保证幂等；dev 用 `ConsoleRenderer`，非 dev 用 `JSONRenderer`，自动适配 observability 后续接入
- **`src/db/migrations/env.py:11-14`** — 通过 `import src.db.models  # noqa: F401` 显式触发 metadata 注册，避免后续 `alembic revision --autogenerate` 漏表

---

## ⚠️ 偏离项

### 偏离 1：Signal 价格字段类型 — `Decimal` vs `float`

- **位置**：
  - `src/contracts.py:215-217`（实现：`Decimal`）
  - `docs/wbs.md:473-475`（旧规格：`float`）
- **问题**：实现选择了 `Decimal`，WBS v1.0 示例写的是 `float`。
- **影响**：单看这次评审，**实现侧是对的，WBS 是过时的**。
- **裁定**：**保留 `Decimal`，反向修订 WBS。**
- **裁定理由**（按重要性排序）：
  1. **架构 §10.1 确定性原则的硬要求**。`float` 是 IEEE 754 二进制浮点，存不下 0.1 / 0.2 / 0.3 这种十进制价位。两次回测哪怕输入完全一致，累积 P&L 也可能在小数末位漂移。`Decimal` 是任意精度十进制，跨平台 / 跨 Python 版本 / 跨硬件结果完全一致。回测可复现性和实盘对账都依赖这个
  2. **契约内部一致性**。`PriceBar.open/high/low/close`（`src/contracts.py:94-98`）、`Position.avg_cost`（`src/contracts.py:183`）、`Trade.price/fee`（`src/contracts.py:196-197`）已经是 `Decimal`。`Signal.buy_range/stop_loss/take_profit` 是同一类语义（价格），跟着 `Decimal` 走才齐整。如果 Signal 用 `float`，下游回测引擎从 Signal 读价格再跟 PriceBar 比较时要做 `float ↔ Decimal` 转换，每次转换都是潜在 bug 点
  3. **金融行业惯例**。Python 官方文档明确推荐 Decimal 处理货币；SQLAlchemy 默认把 `NUMERIC` 列映射到 `Decimal`；Pydantic v2 对 Decimal 序列化为 JSON 字符串保留精度。生态系统都对齐这个选择
  4. **`float` 仍然适用的字段**应当保持 `float`：`position_size_pct`（`src/contracts.py:218`）、`confidence`（`:219`）、`daily_return` / `cumulative_return` / `drawdown` / `sharpe` / 等业绩指标。这些是比例 / 统计量、不是钱、`float` 精度足够、且对 NumPy / Pandas 友好
- **修改要求**：本次评审无代码修改要求。**WBS 文档需要 v1.1 修订**（不在本评审范围，但应在 Architect 对话里同步处理，避免后续 WP 评审继续引用旧 WBS Signal 示例）

### 偏离 2：`SignalORM` 把 `buy_range: tuple` 拍平成两列

- **位置**：
  - `src/contracts.py:215`（Pydantic：`buy_range: tuple[Decimal, Decimal] | None`）
  - `src/db/models.py:176-177`（ORM：`buy_low: Mapped[Decimal | None]` + `buy_high: Mapped[Decimal | None]`）
  - `src/db/migrations/versions/0001_initial_schema.py:205-206`（迁移列定义同上）
- **问题**：Pydantic 模型用 tuple，ORM 用两列。这是关系数据库的合理决定（SQL 列存不了 tuple），但目前**没有 Pydantic ↔ ORM 转换器**。
- **影响**：Phase 0 没有任何读写 Signal 的路径，所以暂时无影响。但 WP-2.7（回测引擎）和 WP-2.8（持仓管理）会同时碰 Pydantic Signal 和 ORM Signal——届时**必须有一个 `SignalRepository`** 来集中处理 `buy_range ↔ (buy_low, buy_high)` 的双向转换。
- **修改要求**：本次评审无代码修改要求。在 WP-2.7 启动 prompt 里**显式要求实现 `SignalRepository` 并在转换层一次性消化这个 seam**，避免每个调用者都自己写转换逻辑。这一条**应进入 WP-2.7 的契约文档**。

### 偏离 3：`verify_invariants.py` whitelist 用路径后缀 equality

- **位置**：`scripts/verify_invariants.py:71-75`
- **问题**：whitelist 用 `relative_path.as_posix() not in allowed_suffixes`，需要严格相等。如果 WP-3.x 把 narrative 模块从 `src/assistant/narrative.py` 移到 `src/assistant/narrative/__init__.py`（包化），check 会静默失效——LLM 调用会被允许但 CI 不再校验它的合法性。
- **影响**：低概率事件，但属于"沉默失败"——比噪声告警更糟糕。
- **修改要求**：本次评审**不要求修改**。在评审通过后，建议 Architect 对话里加一条 follow-up：当 WP-2.4 实施 event_driven 或 WP-3.x 实施 narrative 时，把 whitelist 的匹配语义升级为路径前缀（`startswith` 或 `pathlib.Path.is_relative_to`），并在 Implementer 启动 prompt 里点名 ownership。

### 偏离 4：审计日志仅内存

- **位置**：`src/llm/audit.py:34`（ring buffer，容量 1000）
- **问题**：架构 §10.2 明确"完整审计日志"是 LLM 使用的强制约束之一，目前是内存实现，进程重启即丢失。
- **影响**：Phase 0 无 LLM 真实调用，零实际影响。`README.md:137` 已自我披露推迟到 WP-1.x。
- **修改要求**：无。**记入 WP-1.x 范围**：当数据层落地时，让 `AuditRecord` 成为一张 ORM 表，`audit.record_call` 同时写内存 + DB。

---

## 🔧 修改要求（直接复制给 Claude Code）

```
本次评审：PASS，Phase 0 无代码修改要求。
所有 4 处偏离都属于"WBS 文档过时"或"deferred to next WP"类别，
不阻塞 main 分支已有内容，也不阻塞 WP-1.x / WP-2.x 启动。

下一步：可以并行启动 V0.1 MVP 的工作包。
```

---

## 📋 可执行验证结果

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 单元测试 | `pytest tests/ -v` | **26 passed** in 1.77s |
| 契约 round-trip | 16 个测试覆盖所有 Pydantic 模型 | 全过 |
| LLM Gateway 行为 | `tests/test_llm_gateway.py` 6 项 | 全过（含 model id 校验、audit 记录、fixture 优先） |
| 烟雾测试 | `tests/test_smoke.py` 4 项 | 全过（health 200、ping 200、DB engine resolves、StrategyBase 抽象正确） |
| Lint | `ruff check src/ tests/ scripts/` | All checks passed |
| 格式 | `ruff format --check` | 30 files already formatted |
| 类型检查 | `mypy src/` | No issues found in 23 source files |
| 不变量 | `python scripts/verify_invariants.py` | All architectural invariants OK |
| Migration | `alembic upgrade head`（SQLite） | `→ 0001, initial schema` 干净通过 |
| 文档同步 | `diff regenerated_contracts.md docs/CONTRACTS.md` | 零 diff |
| 敏感信息扫描 | `git log --all -p \| grep -iE "api[_-]?key\|secret\|password\|token"` | 仅占位/文档/约定密码，无真实泄漏 |
| 券商凭证扫描 | `git log --all -p \| grep -iE "broker\|credential\|account_number"` | 仅 .gitignore 模式与文档引用，无真实泄漏 |
| `.env` 追踪 | `git ls-files \| grep -E "\.env$"` | 无输出（正确未追踪） |
| Frontend 配置 | `frontend/tsconfig.json` strict 模式 + React 18 + Tailwind | 结构正确，UI 留 WP-4.x |
| CI 流水线 | `.github/workflows/ci.yml` | lint → format → mypy → verify → migrate → pytest，与本地 `make check` 对齐 |

---

## 🏗 跨 WP 影响

### 需要在 Architect 对话里更新的文档

| 文档 | 修订内容 | 紧迫度 |
|------|---------|--------|
| `docs/wbs.md` | Signal 契约示例（`:467-482`）的 `float` 改为 `Decimal`；同时补齐缺失的 `id` / `market` 字段、把 `direction: Literal[...]` 改成 `direction: SignalDirection`。bump v1.0 → v1.1 | **高**：在 WP-2.x 启动前必须修，否则 WP-2.5 / WP-2.7 评审时会引用旧示例 |
| `docs/wbs.md` 的 LLMGateway 契约示例（`:454-465`） | 补齐 keyword-only 标记 `*` 和 `max_tokens` 参数，与 `src/llm/gateway.py:46-54` 实际签名对齐 | 中：影响 WP-2.4 V0.6 实施 prompt |
| `docs/architecture.md` | **无需修改**。本次评审未触及任何架构铁律 | — |

### 需要在后续 WP 启动 prompt 里落实的事项

1. **WP-1.x（数据层）**：加一条要求——把 `src/llm/audit.py` 的 in-memory ring buffer 升级为 DB-backed 表（解决偏离 4）
2. **WP-2.4（事件驱动 V0.2 calendar-only 部分）**：实施时点名 `src/strategies/event_driven.py` 是 AI 允许路径，verify_invariants 已 whitelist 该路径
3. **WP-2.4 V0.6 + WP-3.x（投资助手）**：实施 narrative 模块时若改成包结构（`narrative/__init__.py`），同步把 verify_invariants whitelist 升级为路径前缀匹配（解决偏离 3）
4. **WP-2.7（回测引擎）+ WP-2.8（持仓管理）** 的契约文档里**显式要求**实现 `SignalRepository`，集中处理 `buy_range: tuple ↔ (buy_low, buy_high)` 双向转换（解决偏离 2）

### Phase 0 解锁的并行启动机会

四层检查全过，所有 35 个 WP 的契约依赖都已就位。下一批可以并行启动：

- **WP-1.1**（美股数据适配器）— 不依赖其他 WP，可独立启动
- **WP-1.3**（宏观数据适配器）— 不依赖其他 WP，可独立启动
- **WP-2.1**（策略基类与因子库）— `StrategyBase` 已就位，可基于 `src/contracts.py` 的因子相关字段开始填充
- **WP-2.7**（回测引擎）— 可基于 `Signal` / `Position` / `Trade` / `PerformanceSnapshot` 契约启动

V0.1 MVP（趋势动量端到端）所需的 WP 链条已经无 blocking issue。

---

## 决议

- [x] **PASS** — 直接合入 main 分支已是当前状态，无回滚或修改要求
- [ ] ITERATE — 不需要

**下一步行动**：
1. 把本评审报告 commit 到 `reviews/wp-0-r1.md`，PR 合并到 main
2. 在 Architect 对话同步更新 `docs/wbs.md` v1.1（Signal 契约 + LLMGateway 契约对齐）
3. 启动下一批 WP（推荐顺序：WP-1.1 → WP-2.1 → WP-2.7 → WP-1.3，可 4 个 Claude Code 窗口并行）

---

## 附录：评审环境

- **Reviewer 工具链**：Linux 容器，Python 3.12.3（项目 pyproject.toml 允许 `>=3.11,<3.13`，3.12 已验证可工作）
- **Reviewer 操作**：`git clone https://github.com/chengzhang950127-png/stock.git stock-review`，工作树位于 commit `37984c9`
- **未跑的检查**：CI 远程结果（GitHub Actions 在仓库改公开后的最新 run 状态）—— 建议合并本评审 PR 时观察一次完整 CI 通过即可
