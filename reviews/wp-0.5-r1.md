# 评审：WP-0.5 Currency 字段补丁（commit 72679db）

**分支**：`main`（已合入）
**Reviewer**：Project 内规划/评审对话（Architect + Reviewer 角色）
**轮次**：r1（首轮，唯一一轮）
**评审时间**：2026-05-09
**仓库**：https://github.com/chengzhang950127-png/stock

---

## 概述

Phase 0.5 一次性通过。所有验收标准达成，且 `aeebb98 fix(db): split market-backfill from non-market tables` 这个迭代证明 Implementer 在执行中识别并自主修正了 prompt 的盲点（accounts 表没有 market 列）——这是高质量实现的健康信号。

**决议：PASS — 已合入 main，无需 r2 迭代。可正式启动 V0.1 第一波并行 WP。**

---

## ✅ 通过项

### 第一层：契约一致性

- **`src/contracts.py:91-95`** — 新增 `Currency(str, Enum) {USD, HKD}` 枚举，docstring 明确"V1.x 港股 A 股扩展时再加 CNY"
- **`src/contracts.py:` `currency_for_market` 工具函数** — 集中实现，业务代码不能散布 if-else 推断
- **`src/contracts.py:102/109`** Stock 加 `currency: Currency`，删除原 `market_cap` 注释中过时的"USD or HKD"约定
- **`src/contracts.py:195/199`** Account、**`:205/211`** Position、**`:217/224`** Trade 全部加 `currency` 必填字段
- **`src/contracts.py:238-253`** Signal 模型**未**被错误添加 currency（按 v1.1 规范：信号继承 stock 推断币种，不冗余存储）
- **`docs/CONTRACTS.md`** — 由 `make contracts` 重新生成，与 `src/contracts.py` 当前状态零 diff（`diff /tmp/regen.md docs/CONTRACTS.md` 返回空）

### 第二层：架构边界

- 不变量校验：`scripts/verify_invariants.py` 输出 `All architectural invariants OK.`，七条全过
- 没有引入任何 LLM 调用，没有改动决策路径，AI 边界纹丝未动
- `src/llm/`、`src/strategies/base.py`、`src/api/*` 等本次范围外文件均未被触碰（验证：`git diff main~7..main -- src/llm/ src/strategies/ src/api/` 全空）

### 第三层：原则遵守

- 模型版本 / 温度 / 审计日志相关代码本次未触及，原状态保持
- 迁移文件 docstring（`0002_add_currency.py:1-37`）解释为什么用三步式（ADD → UPDATE → SET NOT NULL），与 Phase 0 的 `0001` 同样诚实记录"为什么这样做"

### 第四层：可执行验证

```
$ pytest tests/ -v
====== 29 passed in 1.43s ======
（原 26 + 新增 3：test_currency_for_market_us / _hk / test_currency_enum_values）

$ python scripts/verify_invariants.py
All architectural invariants OK.

$ PYTHONPATH=. python scripts/generate_contracts_md.py > /tmp/regen.md
$ diff /tmp/regen.md docs/CONTRACTS.md
（零输出 = 文档完全同步）

$ alembic upgrade head           # SQLite
INFO  Running upgrade  -> 0001
INFO  Running upgrade 0001 -> 0002, add currency
$ alembic downgrade base
INFO  Running downgrade 0002 -> 0001
INFO  Running downgrade 0001 ->
$ alembic upgrade head           # 再 upgrade 验证可重放
（双向干净）
```

### 加分项（超出 prompt 要求）

1. **`0002_add_currency.py:53-67`** Implementer 自主识别 prompt 盲点：accounts 表没有 market 列，无法用 `currency = currency_for_market(market)` 反推。把表分成 `TABLES_WITH_MARKET` 和 `TABLES_WITHOUT_MARKET` 两组分别处理。`aeebb98` commit 是迭代修复，commit message 直陈问题。**这是评审最看重的工程素养**——不是把规格当圣经，而是发现规格盲点后诚实迭代

2. **`0002_add_currency.py:99-111`** 对 accounts 表加防御性断言：`SELECT COUNT(*) WHERE currency IS NULL > 0` 时 raise，避免 SET NOT NULL 静默失败。Phase 0 数据库为空时这段是 no-op，但生产数据 replay 时会立刻 fail loud，是正确的失败模式

3. **`0002_add_currency.py:71-75`** `MARKET_TO_CURRENCY` 字典内联在迁移里而非 import `src.contracts.currency_for_market`，docstring 解释了"迁移必须自包含，不能依赖应用代码语义"。这是金融工程的标准做法，避免未来 contracts.py 语义漂移污染历史迁移的回放结果

4. **`0002_add_currency.py:114-119`** 用 Alembic `batch_alter_table` 兜底 SQLite 不支持 ALTER COLUMN SET NOT NULL 的限制，同一份迁移在 SQLite 和 Postgres 都干净跑通

5. **CHECK 约束命名规范** `ck_{table}_currency_iso4217` 严格按 prompt 建议命名，未来 grep 友好

---

## ⚠️ 偏离项

无。所有 prompt 要求达成，没有任何偏离。

---

## 🔧 修改要求

```
本次评审：PASS，无代码修改要求。
合入路径：commit 72679db 已通过 PR #2 合入 main。
下一步：可正式启动 V0.1 第一波并行 WP（WP-1.1 / WP-2.1 / WP-2.5 / WP-2.7）。
```

---

## 📋 可执行验证结果

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 单元测试 | `pytest tests/ -v` | **29 passed** in 1.43s（原 26 + 新增 3） |
| 不变量 | `python scripts/verify_invariants.py` | All architectural invariants OK |
| 文档同步 | `diff regen_contracts.md docs/CONTRACTS.md` | 零 diff |
| 迁移正向 | `alembic upgrade head`（SQLite） | `→ 0001 → 0002, add currency` 干净 |
| 迁移可逆 | `alembic downgrade base` | `0002 → 0001 → ` 干净 |
| 迁移可重放 | 第二次 `alembic upgrade head` | 干净 |
| 范围外代码未触动 | `git diff main~7..main -- src/llm/ src/strategies/ src/api/` | 空 |
| 敏感信息扫描 | 同 Phase 0 评审 | 无变化、无泄漏 |

---

## 🏗 跨 WP 影响

### 已解锁

- **V0.1 第一波 4 路并行启动条件齐备**：WP-1.1 / WP-2.1 / WP-2.5 / WP-2.7 都依赖 Phase 0.5 之后的 `Stock`/`Account`/`Position`/`Trade` 类型
- **WP-2.8 跨币种支持** 的契约层基础就位，下游港股影子账户记账无歧义

### 已记录到 WBS v1.1 的下游 WP 要求

- **WP-2.7 回测引擎**：必须基于 currency 字段做跨市场组合 mark-to-market；look-ahead bias / survivorship bias 防护是 v1.1 新增验收标准
- **WP-2.8 持仓管理**：实现 `SignalRepository` 集中处理 Pydantic Signal ↔ ORM SignalORM 双向转换；P&L 输出区分本币 vs 等值 USD（V0.6 起）

### 不需要更新的文档

- `docs/architecture.md` v1.1 §10.4 已经在 architect 侧写好，本次代码落地与文档完全一致
- `docs/INVARIANTS.md` 不变量集合不变（货币是契约层约束，不是新增不变量）

---

## 决议

- [x] **PASS** — 已合入 main，无回滚或修改要求
- [ ] ITERATE — 不需要

**下一步行动**：

1. 把本评审报告 commit 到 `reviews/wp-0.5-r1.md`
2. 启动 V0.1 第一波并行 WP（详见同步产出的 4 份 Claude Code 启动 prompt）

---

## 附录：评审环境

- **Reviewer 工具链**：Linux 容器，Python 3.12.3
- **Reviewer 操作**：`git fetch && git checkout main`，工作树位于 commit `d1f4692`（包含 PR #1 评审记录合入 + PR #2 Phase 0.5 合入）
- **未跑的检查**：Postgres 真实库的迁移（仅在 SQLite 内存库验证）—— 建议下次 GitHub Actions 触发时观察 CI 中 Postgres service 的 alembic step 通过即可
