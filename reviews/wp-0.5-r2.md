# 评审：WP-0.5 货币字段补丁（branch wp-0.5-currency, HEAD ce28be9）

**分支**：`wp-0.5-currency`
**Reviewer**：Project 内评审对话（Architect + Reviewer 角色）
**轮次**：r2（接续 r1 的 ITERATE 决议）
**评审时间**：2026-05-10
**Implementer 自报**：本机已跑完整 acceptance suite，caveat 1 兑现

---

## 概述

r1 的两条 BLOCKING 偏离都修干净了。两个 fix commit 范围极窄、与 r1 给出的 §修改要求 字面对齐；本机 acceptance + Reviewer 端复跑全过；schema 验证 4 个表均有 `currency VARCHAR(3) NOT NULL` + 命名 CHECK 约束；migration upgrade → downgrade → upgrade 三段干净可重放；CONTRACTS.md 与 generator 输出仍零 diff。

**决议：PASS — 直接合入 main，解锁 V0.1 数据层和策略层 WP 启动。**

---

## ✅ 偏离修复确认

### 偏离 1（r1 BLOCKING）→ 修复确认

- **修复 commit**：`aeebb98 fix(db): split market-backfill from non-market tables in migration 0002`
- **位置**：`src/db/migrations/versions/0002_add_currency.py`
- **r1 期望的修复**：拆 `TABLES` 为 `TABLES_WITH_MARKET` + `TABLES_WITHOUT_MARKET`；step 2a 仅对前者跑 backfill UPDATE；step 2b 对后者用 `SELECT COUNT(*) WHERE currency IS NULL` 做 fail-loud guard；step 1/3 + downgrade 走 `ALL_TABLES`
- **r2 实际修复**：与 r1 §修改要求 #1 字面字符级一致——同样的 `TABLES_WITH_MARKET` / `TABLES_WITHOUT_MARKET` / `ALL_TABLES` 命名、同样的 step 2a / step 2b 拆分、同样的 `op.get_bind().execute(sa.text(...)).scalar()` + `RuntimeError(f"...")` guard、同样的注释结构。**diff 无任何 drift**
- **执行验证**：

```
$ rm -f /tmp/r2.db
$ DATABASE_URL="sqlite+pysqlite:////tmp/r2.db" alembic upgrade head
INFO  Running upgrade  -> 0001, initial schema
INFO  Running upgrade 0001 -> 0002, add currency

$ alembic downgrade base
INFO  Running downgrade 0002 -> 0001, add currency
INFO  Running downgrade 0001 -> , initial schema

$ alembic upgrade head     # replay
INFO  Running upgrade  -> 0001, initial schema
INFO  Running upgrade 0001 -> 0002, add currency
```

- **额外验证（超出 r1 要求）**：我手工模拟 future-data 场景测试 fail-loud guard：先 `alembic upgrade 0001`，往 `accounts` 表插入一行无 currency 的数据，然后 `alembic upgrade 0002`，guard 正确捕获并报错：

```
CORRECT: guard fired — 'accounts' has 1 rows without currency. 
Backfill them via a data migration before re-running 0002.
```

这意味着该 migration 在 V0.7 实施账户落地（accounts 表第一次有真实数据）时如果忘了在前置 migration 里 backfill，会**显式爆炸而非静默 SET NOT NULL 失败**——desired contract

### 偏离 2（r1 BLOCKING）→ 修复确认

- **修复 commit**：`ce28be9 fix(tests): use ASCII docstring in test_currency_enum_values (RUF002)`
- **位置**：`tests/test_contracts.py:156`
- **r1 期望的修复**：去掉 fullwidth 中文逗号 `，`
- **r2 实际修复**：取 r1 §修改要求 #2 的 option B（整段改英文），最稳——避免后续测试再写中文又踩 RUF002：
  ```python
  """ISO 4217 three-letter codes; expand this set when V1.x adds CNY."""
  ```
- **执行验证**：`ruff check src/ tests/ scripts/` 输出 `All checks passed!`

---

## ✅ 全量 acceptance 复验（Reviewer 端）

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 单元测试 | `pytest tests/ -v` | **29 passed** in 1.72s |
| Lint | `ruff check src/ tests/ scripts/` | **All checks passed!** ✓ |
| 格式 | `ruff format --check src/ tests/ scripts/` | 30 files already formatted |
| 类型检查 | `mypy src/` | No issues found in 23 source files |
| 不变量 | `python scripts/verify_invariants.py` | All architectural invariants OK |
| **Migration upgrade** | `alembic upgrade head` (空 SQLite) | ✓ 0001 → 0002 干净 |
| **Migration downgrade** | `alembic downgrade base` | ✓ 0002 → 0001 → empty 干净 |
| **Migration replay** | `alembic upgrade head` 再来一次 | ✓ 干净可重放 |
| **Schema 验证** | `sqlite3 .schema` for 4 tables | ✓ 全部 `currency VARCHAR(3) NOT NULL` + 命名 CHECK |
| **Future-data guard 验证** | accounts 注入 1 行后 upgrade | ✓ guard 触发，错误信息描述清楚 |
| 文档同步 | `diff /tmp/regen_r2.md docs/CONTRACTS.md` | 零 diff |

Schema 实测输出（grep `currency` from `sqlite_master`）：

```
stocks:    currency VARCHAR(3) NOT NULL
           CONSTRAINT ck_stocks_currency_iso4217 CHECK (currency IN ('USD', 'HKD'))

accounts:  currency VARCHAR(3) NOT NULL
           CONSTRAINT ck_accounts_currency_iso4217 CHECK (currency IN ('USD', 'HKD'))

positions: currency VARCHAR(3) NOT NULL
           CONSTRAINT ck_positions_currency_iso4217 CHECK (currency IN ('USD', 'HKD'))

trades:    currency VARCHAR(3) NOT NULL
           CONSTRAINT ck_trades_currency_iso4217 CHECK (currency IN ('USD', 'HKD'))
```

CHECK 约束命名遵循 `ck_{table}_currency_iso4217` 约定（grep-friendly，r2 caveat 自报点 #3 兑现）。

---

## 🏗 跨 WP 影响

### Architect 文档**不需要任何更新**

WP-0.5 全程沿着 `architecture.md v1.1 §10.4` + `wbs.md v1.1 Phase 0.5` 的规格走，未触及任何架构原则。`String(3) vs CHAR(3)` 的字面偏离已在 r1 的"原则遵守"段接受（SQLAlchemy 没有干净跨方言 CHAR；ISO 4217 永远 3 字符无 trailing space 问题；语义等价）。

### V0.1 解锁

合入 main 后，下列 4 个 V0.1 WP 立即可以并行启动：

- **WP-1.1**（美股数据适配器）— `Stock(currency=Currency.USD)` 可用
- **WP-1.2**（港股数据适配器）— `Stock(currency=Currency.HKD)` 可用
- **WP-2.7**（回测引擎）— `Position` / `Trade` 持有 currency 字段，可正确做单币种 mark-to-market；跨币种 P&L 归因留给 V0.6（FXRate 注入点已在 architecture §10.4 #4 保留）
- **WP-2.8**（持仓管理与 P&L）— Account 的 `currency` 字段就位；架构 §4.3 "港股影子账户也以 100,000 USD 等值起始"在 V0.2 实施时直接落到 ORM

### 给后续 WP Implementer 的小提示

- 业务代码**绝不**手工拼 `if market == US: return USD`，统一通过 `from src.contracts import currency_for_market` 调用（`src/contracts.py:91`，docstring 已显式禁止 inline 分支）
- Account 的 currency 不是从 market 推断的（accounts 没有 market 列）。新建 Account 时调用方**必须显式传 currency**——这是 r1 的 BLOCKING 揭示的边界
- 未来若新增 `FXRate` 对象（V0.6 投资助手做美港合计组合视角），`currency` 字段是它的 join key，不要用 market 做 join

---

## 📈 流程改进观察

r1 的 caveat 1（"本机未跑 acceptance"）直接命中两个真实回归。Implementer 在 r2 兑现承诺：先 install uv → 复现两条 regression 确认 reviewer 描述准确 → 应用精确修复 → 跑完整 acceptance → 才 push。这是健康的反馈环路。

**建议在 Architect 对话同步到 `review-protocol.md` 的"实现者职责"段落（v1.x 微修订）**：

> **强制 acceptance gate**：任何 WP 推送到远程前，Implementer 必须本机至少跑通：
> - `make check`（lint + format + mypy + pytest + verify_invariants）
> - `alembic upgrade head` → `downgrade base` → `upgrade head` 三段（如果该 WP 触及 ORM 或迁移）
> - `python scripts/generate_contracts_md.py` 与 `docs/CONTRACTS.md` 零 diff（如果该 WP 改了 Pydantic 模型）
>
> 推送前未本机验证而由 Reviewer 端首次发现的 BLOCKING 缺陷，自动多算一轮迭代。这不是惩罚，是反馈对齐：让 Implementer 端的修复成本与 Reviewer 端发现的成本接近，避免分布式开发的 free-rider 问题。

WP-0.5 r1 → r2 验证了这一点，是规则化的好时机。

---

## 决议

- [x] **PASS** — 合入 main，归档 WP-0.5
- [ ] ITERATE

**下一步行动**：

1. PR `wp-0.5-currency` → `main` 合入（用 squash 还是 merge commit 都可——3 commit 原 + 2 commit 修复，5 个 commit 的故事线本身可读，我倾向用 merge commit 保留完整历史）
2. 可选：在 Architect 对话同步把 `review-protocol.md` 的"实现者职责"段加上"强制 acceptance gate"（v1.x 微修订），让 r1 的教训规则化
3. **启动 V0.1 MVP 链条**：4 路并行 Claude Code 窗口可以同时开始 WP-1.1 / WP-2.1 / WP-2.7 / WP-1.3，每路对应一个独立的「[评审] WP-X.X」对话。所有契约依赖已就位，无 blocking issue

---

## 附录：评审过程

- `git fetch && git checkout origin/wp-0.5-currency`，HEAD = `ce28be9`
- 两个 fix commit 各看一次 diff，对照 r1 §修改要求 字面比对——零 drift
- 全量 acceptance 复跑 11 项检查，全过
- 额外验证 fail-loud guard（不在原 r1 acceptance 列表里）：手工注入数据，确认 RuntimeError 触发且消息清楚
- 写本评审报告
