# 评审协议

**文档定位**：定义 Architect / Implementer / Reviewer 三方的协作机制，让 Claude Code 多窗口并行开发可控且一致。

**修订规则**：流程改动必须更新本文档。

---

## 三方角色

**Architect（产品规划者）**
- 决定架构、版本规划、WBS、契约和不变量
- 在 Project 内的"规划对话"承担此角色
- 我（Claude）配合用户共同行使

**Implementer（实现者）**
- 在每个 WP 的特性分支上写代码
- 由 Claude Code 在用户的开发机上承担
- 不做架构决策，只在已定契约下实现

**Reviewer（评审者）**
- 评审 Implementer 产出，校验契约、不变量、可执行性
- 在 Project 内的"评审对话"承担此角色
- 我（Claude）独立行使（偶尔升级到 Architect 处理规划侧问题）

**关键原则**：所有架构变更必须先经 Architect 拍板更新文档，再驱动 Implementer 实施，最后由 Reviewer 校验一致性。三方角色可以由不同的对话承担，避免上下文污染。

---

## Git 工作流

### 仓库设置

- **公开 GitHub 仓库**（强烈建议——见 `architecture.md` 第 11 节关于安全的说明）
  > **⚠️ 现行偏离**：项目目前实际为 **private 仓库**
  > （[chengzhang950127-png/stock](https://github.com/chengzhang950127-png/stock)）。
  > 详细原因和何时切回 public 的判据见 `architecture.md` §10.3 注脚。
  > 本协议其他条款（评审记录入 git、敏感信息扫描等）在 private 模式下**不变**。
- 主分支 `main` 始终保持可运行状态
- 每个 WP 一个特性分支，命名 `wp-X.X-描述`，例如 `wp-2.3-trend-momentum`

### 不进 git 的内容

- `.env`（API keys、DB 密码、各种 secrets）
- 券商凭证、用户登录密码
- 真实账户持仓数据
- LLM API key
- 个人交易记录

`.gitignore` 必须在 Phase 0 第一个 commit 就配齐，模板见 Phase 0 prompt。

### 评审记录入 git

每次评审报告 commit 到 `reviews/wp-X.X-rN.md`（N 为迭代轮数）。好处：

- 评审历史本身是项目资产
- 多次迭代天然形成"决策日志"
- 接手时能看到完整推演脉络

---

## 单个 WP 的标准循环

```
Architect 写启动 prompt
    ↓
Implementer（Claude Code 会话）执行
    ↓
推送特性分支
    ↓
通知 Reviewer
    ↓
Reviewer 拉取 + 评审 + 跑测试
    ↓
评审报告（pass / iterate）
    ↓
若 iterate：Implementer 修复 → 推送 → Reviewer 增量评审
若 pass：合并到 main，归档 WP
```

### 阶段 1：起跑

Architect 给 Implementer 一份启动 prompt，包含：

- 上下文摘要（项目背景、当前所处版本）
- 必须遵守的契约文档引用
- 本 WP 的范围、输入、输出、依赖
- 验收标准（来自 WBS）
- 不要做什么的列表
- 建议的实现路径

格式参考 `phase0_claude_code_prompt.md`。

### 阶段 2：执行

用户拿启动 prompt 开 Claude Code 会话，Claude Code 在特性分支上写代码。这一阶段 Architect 和 Reviewer 不参与。

Implementer 应当：

- 先写测试再写实现（TDD），或至少先写接口 + 用例再写实现
- 有疑问时优先翻 `CONTRACTS.md` 和 `INVARIANTS.md`，而不是自己发明
- 遇到契约缺失时停下来，标记 `# TODO(architect): contract missing for X`
- 完成后 push 分支，写一段简明的 PR 描述

### 阶段 3：交回

用户告诉 Reviewer 对话："review branch wp-X.X-name"。

提供方式三选一：

1. **直接告诉分支名**（推荐）— Reviewer 自己 fetch
2. **粘贴关键文件内容** — 适合很小的 WP 或快速 spot-check
3. **粘贴 git diff** — 适合增量修复

### 阶段 4：评审

Reviewer 做四层检查：

#### 第一层：契约一致性

- 类型签名、字段名、JSON Schema 是否匹配 `CONTRACTS.md`
- Pydantic 模型是否复用，没有重复定义
- 公开接口的命名是否符合项目约定

```bash
git diff main..HEAD -- src/contracts.py    # 契约动了吗？
grep -rn "class.*StrategyBase" src/        # 继承结构正确吗？
```

#### 第二层：架构边界

- AI 调用是否仅在两个允许位置（事件驱动 + 助手叙事）
- 所有 LLM 调用是否走 `LLMGateway`
- Schema 校验是否到位
- 是否有禁止的依赖（核心代码 import LLM 库等）

```bash
grep -rn "import litellm\|from openai\|import anthropic" src/strategies/
grep -rn "import litellm\|from openai\|import anthropic" src/portfolio/
grep -rn "llm\.complete\|client\.complete" src/  # 应该都通过 Gateway
```

#### 第三层：原则遵守

- 模型版本是否写死（不用 `claude-3-5-sonnet`，必须 `claude-3-5-sonnet-20241022`）
- 温度是否归零
- 审计日志是否到位
- 降级路径是否有

```bash
grep -rn "model=" src/llm/
grep -rn "temperature=" src/llm/
grep -rn "log\|audit" src/llm/
```

#### 第四层：可执行验证

- 单元测试通过
- 集成测试通过
- 真跑一遍 sample 用例
- 输出范围合理

```bash
pytest tests/ -v
pytest tests/ --tb=short

# 真跑回测
python -m run --strategy <strategy_name> --start 2020-01-01 --end 2024-12-31

# 验证关键指标
python -c "from src.backtest.metrics import sharpe_ratio; assert ..."
```

### 阶段 5：迭代

Reviewer 输出评审报告。若 pass，合并到 main，归档 WP。若需 iterate，Implementer 拿报告改。

---

## 评审报告模板

```markdown
# 评审：WP-X.X 简短描述（commit <SHA>）

**分支**：wp-X.X-name
**Reviewer**：Project 内评审对话
**轮次**：rN（第 N 轮迭代）

## ✅ 通过项

- [明确说什么实现得对]
- [...]

## ⚠️ 偏离项

### 偏离 1：[简短描述]
- **位置**：`src/path/to/file.py:行号`
- **问题**：[详细描述]
- **影响**：[为什么 matter，short-term + long-term]
- **修改要求**：[去 Claude Code 说什么具体的话]

### 偏离 2：...

## 🔧 修改要求（直接复制给 Claude Code）

```
请做以下修改：
1. 在 src/strategies/trend_momentum.py:47，把硬编码的 252 改成 self.parameters.momentum_window
2. 在 screen() 里加 _has_sufficient_history() 过滤新股
3. ...
```

## 📋 可执行验证结果

- pytest: ✅ 全过 / ❌ 失败 [失败信息]
- sample 回测：[关键指标 + 是否在合理范围]
- 集成测试：[是否破坏其他 WP]

## 🏗 跨 WP 影响

- 与其他分支契约一致性：✅ / ⚠️
- 是否需要更新 CONTRACTS.md：是 / 否
- 是否影响下游 WP：[列出]

## 决议

- [ ] PASS — 合并到 main
- [x] ITERATE — 期待第 N+1 轮修复
```

将报告 commit 到 `reviews/wp-X.X-rN.md`，让用户和 Implementer 同时可见。

---

## 多分支并行的玩法

假设你同时开了 4 个 Claude Code 窗口分别做 WP-1.1（美股数据）、WP-1.3（宏观数据）、WP-2.3（趋势动量）、WP-2.7（回测引擎），4 个分支独立 push。

Reviewer 处理方式：

```bash
git fetch --all
git branch -a   # 看到所有远程分支

# 评审 WP-1.1
git checkout wp-1.1-us-data
pytest tests/data/test_us_adapter.py
# 写评审报告 reviews/wp-1.1-r1.md

# 评审 WP-1.3
git checkout wp-1.3-macro-data
# ...

# 跨分支冲突检查（贴代码评审做不到）
git diff wp-1.1-us-data wp-2.3-trend-momentum -- src/contracts.py
git merge-base wp-1.1-us-data wp-2.3-trend-momentum  # 共同祖先

# 模拟整合
git checkout -b integration-test
git merge wp-1.1-us-data wp-1.3-macro-data wp-2.3-trend-momentum
pytest tests/  # 整合后是否还能跑
```

**跨分支冲突识别**是贴代码评审做不到的——能在 merge 到 main 之前就发现整合冲突。

---

## 评审会话的对话边界

为了避免对话上下文污染：

### 一个对话只评审一个 WP 系列

例如「[评审] V0.1-WP-2.3 趋势动量」从 r1 到合并到 main 都在同一对话里完成。Reviewer 在那个对话里能看到所有迭代历史。

### 不要把多个不相关 WP 混在一个评审对话里

如果同时评审 WP-2.3 和 WP-4.1，会让 Reviewer 频繁切换上下文，效率反而下降。

### 当对话过长时

单个 WP 经过 5+ 轮迭代还没合并是异常信号。这时候应该：

1. 暂停，回 Architect 对话评估为什么这个 WP 卡住了
2. 是否应该拆成两个 WP？
3. 是否契约本身有问题？
4. 是否 Implementer 需要不同的启动 prompt？

避免在同一个评审对话里无止境迭代。

---

## 意见不一致时的处理

**Implementer 觉得契约不合理**

Implementer（Claude Code）在执行时可能发现按契约实现会遇到困难，提出修改契约。这种情况：

1. Reviewer 不应直接接受 — 这跨过了角色边界
2. Reviewer 应当回到 Architect 对话讨论是否真的需要改契约
3. 如果决定改契约，先更新 `CONTRACTS.md`，再让所有受影响 WP 同步评审
4. 最后才让 Implementer 重新提交

**Reviewer 觉得 Implementer 偏离了规划**

但 Implementer 有充分理由（性能、稳定性、清晰度）：

1. 评审报告里诚实记录"按规划做更好"的理由
2. 一并记录 Implementer 的反对理由
3. 升级到 Architect 决策
4. 决策结果更新到契约文档（如果改了规划）或 Implementer 修改（如果维持规划）

**坚守的底线**

- AI 边界（仅两个调用点）
- LLM Gateway 中央化
- Schema 强制校验
- 模型版本固定
- 温度归零

这五条任何情况都不能让步。其他的可以根据上下文协商。

---

## 公开仓库的安全检查

每次评审都跑一遍敏感信息扫描：

```bash
# 检查是否有 API key 或密钥泄漏
git log --all -p | grep -iE "api[_-]?key|secret|password|token" | head -20

# 检查 .env 是否被错误 commit
git ls-files | grep -E "\.env$"

# 检查券商凭证
git log --all -p | grep -iE "broker|account|credential"

# git-secrets 工具集成（推荐）
git secrets --scan
```

发现泄漏立即处理：

1. revoke 泄漏的 key
2. 用 `git filter-repo` 或 BFG 从历史清除
3. force push 重写历史
4. 通知所有 collaborator 重新 clone

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 初始 | v1.0 | 三方角色 + git 工作流 + 评审标准 |
