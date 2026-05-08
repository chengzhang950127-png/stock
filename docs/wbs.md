# 工作分解结构（WBS）

**文档定位**：把整个项目分解成 ~35 个工作包（Work Package, WP），每个 WP 自包含、可独立验收，专为多个 Claude Code 会话并行开发设计。

**修订规则**：WP 范围调整必须更新本文档。新增 WP 必须明确依赖关系。

---

## 整体节奏

| 阶段 | 内容 | 并行度 | 估时（单人单会话连续工作） |
|------|------|--------|----------|
| Phase 0 | 基础脚手架与共享契约 | 串行（1 会话） | 0.5-1 天 |
| Phase 1 | 数据层 | 5 路并行 | 4-6 天 |
| Phase 2 | 策略与组合 | 6-8 路并行 | 6-9 天 |
| Phase 3 | 投资助手 | 4 路并行 | 3-5 天 |
| Phase 4 | 应用层 | 前后端 2-3 路 | 5-7 天 |
| Phase 5 | 账户系统（独立） | 任意时间 | 4-6 天 |

3-4 个并行 Claude Code 窗口同时干活：端到端 3-5 周完成核心系统（Phase 0-4），账户系统再加 1 周。

---

## Phase 0: 基础脚手架（必须串行，1 会话完成）

**目标**：定义所有后续工作的接口契约和共享基础设施。完成前不能开并行窗口。

### WP-0.1 项目脚手架

- **范围**：仓库结构、Python 项目（`pyproject.toml` + uv/poetry）、前端项目（package.json + Vite + React + TS + Tailwind）、Docker Compose 开发环境（含 Postgres）、CI/lint/format 配置（ruff + black + mypy + pytest）、目录约定
- **输入**：无
- **输出**：可用的开发环境，`make dev` 一键启动
- **依赖**：无
- **验收**：
  - `git clone && uv sync && pytest` 通过
  - `docker compose up -d` 启动 Postgres
  - `make dev` 启动后端 dev server
- **估时**：1-2 个 Claude Code 会话

### WP-0.2 共享数据模型与 ORM

- **范围**：核心领域对象的 Pydantic 模型 + SQLAlchemy ORM。包括 `Stock`、`PriceBar`、`Strategy`（含 type 枚举：BUILT_IN/CUSTOM；status 枚举：ACTIVE/ARCHIVED/DELETED）、`StrategyParameters`（JSON Schema 化）、`Account`（type: SHADOW/LIVE）、`Position`、`Signal`（含 buy_range/stop_loss/take_profit）、`Trade`、`PerformanceSnapshot`、`Regime`、`AssistantAdvice`、`PerformanceArchive`
- **输入**：架构文档
- **输出**：`src/contracts.py`（Pydantic 模型）+ `src/db/models.py`（ORM）+ Alembic 初始迁移
- **依赖**：WP-0.1
- **验收**：
  - 所有 Pydantic 模型 round-trip 测试通过（serialize → deserialize → equal）
  - Alembic 迁移可以创建空数据库
  - `python -c "from src.contracts import *"` 无报错
- **估时**：2-3 个 Claude Code 会话

### WP-0.3 LLM Gateway 抽象

- **范围**：`LLMGateway` 抽象类 + 单一调用入口 + Mock 实现（V0.1-V0.5 用）+ 后续接 OpenRouter 或 OpenAI 的真实实现（V0.6 完成）
- **输入**：架构文档（AI 边界原则）
- **输出**：`src/llm/gateway.py` + `src/llm/mock.py` + 单元测试
- **依赖**：WP-0.1, WP-0.2
- **验收**：
  - 接口签名符合契约：`async def complete(prompt, response_schema, model, temperature)`
  - Mock 实现返回预定义 schema 实例
  - 调用日志、错误处理、降级路径完整
- **估时**：1-2 个 Claude Code 会话

### WP-0.4 配置与密钥管理

- **范围**：`.env` + Pydantic Settings、加密存储约定、不同环境（dev/test/prod）的配置切换、`.env.example` 模板
- **输入**：无
- **输出**：`src/config.py` + `.env.example`
- **依赖**：WP-0.1
- **验收**：
  - `Settings()` 可从 `.env` 加载
  - 缺失必填字段有明确报错
  - `.env.example` 涵盖所有需要的字段
- **估时**：0.5 个会话

### WP-0.5 契约文档生成

- **范围**：从 Pydantic 模型自动生成 `CONTRACTS.md` + 手写补充 `INVARIANTS.md`
- **输入**：WP-0.2 完成
- **输出**：仓库根目录的 `CONTRACTS.md` 和 `INVARIANTS.md`
- **依赖**：WP-0.2
- **验收**：
  - `CONTRACTS.md` 自动生成脚本能跑（`make contracts`）
  - `INVARIANTS.md` 包含所有架构不变量条目
- **估时**：0.5 个会话

**Phase 0 总验收**：所有后续 WP 可以基于这套接口和工具开始开发，无 blocking issue。

---

## Phase 1: 数据层（5 路并行）

每个 WP 都消费 Phase 0 的契约，输出符合 ORM 模型的数据。互相之间无依赖。

### WP-1.1 美股行情适配器

- **范围**：YFinance 接入美股日线、复权处理、基本面（PE/PB/ROE/EPS）、财报数据。归一化到 `PriceBar` 和 `Stock` 模型，写入数据库。需要重试、限流、缓存逻辑
- **输入**：股票代码列表（从 universe 配置）
- **输出**：DB 中的 PriceBar 和 Stock 记录
- **依赖**：Phase 0
- **验收**：
  - `python -m data fetch --market us --period 5y` 拉取 S&P 500 + 主要 ETF 5 年数据
  - 数据完整性检查通过（无空缺日、价格合理范围）
  - 单元测试覆盖 adapter 接口
- **估时**：2 个会话

### WP-1.2 港股行情适配器

- **范围**：通过 AkShare 或 Tushare Pro 拉港股，加上**南向资金净流入**数据（这是港股策略的核心因子）、**AH 溢价计算**（同股美/港价差）、行业分类
- **输入**：港股代码列表
- **输出**：DB 中的港股 PriceBar、Stock、SouthboundFlow、AHPremium 记录
- **依赖**：Phase 0
- **验收**：
  - 拉取恒指成分股 + 主要 ETF 5 年数据
  - 南向资金数据每日更新
  - AH 溢价计算正确（抽查 5 只对比 Wind 等公开数据）
- **估时**：2-3 个会话

### WP-1.3 宏观数据适配器

- **范围**：FRED API 拉美国宏观（CPI、PMI、10Y 收益率、失业率、PCE）、央行 OMO 数据。这些是 Regime 分类器的输入
- **输入**：宏观指标配置列表
- **输出**：DB 中的 MacroIndicator 记录
- **依赖**：Phase 0
- **验收**：
  - 主要美国宏观指标 5 年历史数据完整入库
  - 数据更新逻辑正确（不重复、不遗漏）
- **估时**：1-2 个会话

### WP-1.4 新闻事件采集器

- **范围**：财经新闻流（Alpha Vantage News 或 Polygon News）、FOMC 日历、财报日历、监管公告。**这一层只采集，不解析**——解析在事件驱动策略和投资助手里做（V0.6 才接 AI）
- **输入**：标的池 + 关键事件类型
- **输出**：DB 中的 RawNews、CalendarEvent 记录
- **依赖**：Phase 0
- **验收**：
  - 当日新闻流入库（前期可拉历史 6 个月）
  - 财报日历每周更新
  - FOMC 日历全年覆盖
- **估时**：2 个会话

### WP-1.5 数据存储与缓存

- **范围**：DB 连接池、Alembic 迁移管理、缓存层（V0.x 用 in-memory + 文件 JSON，V1+ 可换 Redis）、数据完整性检查任务（每日运行）
- **输入**：数据模型
- **输出**：数据访问层（Repository 模式）+ 缓存装饰器
- **依赖**：Phase 0
- **验收**：
  - 所有数据查询走 Repository
  - 重复查询有缓存命中
  - 数据完整性检查每日产出报告
- **估时**：1-2 个会话

**Phase 1 总验收**：用 Python REPL 可以查询任意一只美港股最近 5 年日线、最新基本面、最近 30 天的相关新闻和事件，宏观数据齐全。

---

## Phase 2: 策略与组合（6-8 路并行）

项目最大的阶段，最适合 Claude Code 多窗口并行的地方。

### WP-2.1 策略基类与因子库

- **范围**：`StrategyBase` 抽象类（`screen()`、`generate_signals()`、`exit_rules()`、`get_score()` 等接口）、因子计算工具库（PE、PB、ROE、动量、ATR、相对强弱、移动平均、波动率、盈利质量等纯函数）
- **输入**：契约文档
- **输出**：`src/strategies/base.py` + `src/strategies/factor_lib.py`
- **依赖**：Phase 0, WP-1.1
- **验收**：
  - 抽象类定义符合契约
  - 因子库每个函数有单元测试
  - 因子计算结果可重现（相同输入 → 相同输出）
- **估时**：2-3 个会话

### WP-2.2 价值反转策略

- **范围**：`ValueReversionStrategy` 实现。美股版重点用 FCF Yield、Buyback Yield、ROIC-WACC；港股版加 AH 溢价、南向资金、红利质量。可配置参数：行业过滤、市值范围、估值阈值、调仓频率
- **输入**：因子库 + 数据
- **输出**：`src/strategies/value_reversion.py`
- **依赖**：WP-2.1
- **验收**：
  - 继承 `StrategyBase` 完整实现
  - 在 SP500 + 恒指成分股 5 年数据上跑回测，年化收益、夏普、最大回撤在合理范围
  - 单元测试覆盖核心逻辑
- **估时**：2-3 个会话

### WP-2.3 趋势动量策略

- **范围**：12-1 动量、盈利上修、量能突破、200 日均线为核心因子。美股可加 Magnificent 7 集中度过滤；港股加南向资金 momentum
- **输入**：因子库 + 数据
- **输出**：`src/strategies/trend_momentum.py`
- **依赖**：WP-2.1
- **验收**：
  - 继承 `StrategyBase` 完整实现
  - 在 5 年数据上跑回测，结果在合理范围
  - 单元测试覆盖核心逻辑
- **估时**：2-3 个会话

### WP-2.4 事件驱动策略

- **范围**：分两版实现。**V0.2 的 calendar-only 版本**：只用结构化事件（财报日、FOMC 日、监管公告日历）；**V0.6 的 AI 版本**：扫描新闻流 → 调用 LLM Gateway 的事件解析 → 结构化事件元数据 → 规则引擎匹配相关股票 → 量价确认后产出信号
- **输入**：因子库 + 事件数据 + LLM Gateway（V0.6）
- **输出**：`src/strategies/event_driven.py`
- **依赖**：WP-2.1, WP-1.4, WP-0.3
- **验收**：
  - V0.2 版本：能基于日历事件产出合理信号
  - V0.6 版本：LLM 输出仅作为信号生成的输入，最终决策由代码规则二次确认
  - 单元测试 + LLM 失败降级测试
- **估时**：3-4 个会话（分两次完成，V0.2 + V0.6）

### WP-2.5 信号生成工具

- **范围**：所有策略共享的入场出场计算工具。买入区间（基于支撑/压力 + 当前价位）、止损（基于 ATR 倍数或固定百分比）、止盈（基于风报比或目标涨幅）、仓位（凯利公式或固定比例）。**纯数学，无 AI**
- **输入**：价格数据
- **输出**：`src/strategies/signal_tools.py`
- **依赖**：WP-2.1
- **验收**：
  - 每个工具函数有单元测试
  - 边界条件（缺数据、新股、停牌）处理正确
- **估时**：1-2 个会话

### WP-2.6 自定义策略对象

- **范围**：V0.5 引入。custom 策略 = 4 套内置策略的 4 维加权组合 `(w_value, w_momentum, w_event, w_index)`。每天对每只候选股票的综合得分 = 加权求和各内置策略的得分。继承 `StrategyBase`，但内部组合现有策略
- **输入**：内置策略对象
- **输出**：`src/strategies/custom_blend.py`
- **依赖**：WP-2.2, WP-2.3, WP-2.4, WP-2.10
- **验收**：
  - 4 维加权组合数学正确
  - 权重和必须为 1（校验）
  - 在 UI 创建后能立即跑起来
- **估时**：1-2 个会话

### WP-2.7 回测引擎

- **范围**：向量化回测核心（NumPy + Pandas）、滑点/手续费建模、walk-forward 验证框架、多策略并行回测调度
- **输入**：策略对象 + 历史数据
- **输出**：`src/backtest/engine.py` + `src/backtest/metrics.py` + `PerformanceSnapshot` 序列
- **依赖**：WP-2.1, WP-1.x
- **验收**：
  - 在 SPY 5 年数据上跑 buy-and-hold 回测，结果对得上 Yahoo Finance 公开数据（误差 < 0.5%）
  - 多策略并行回测无相互干扰
  - 滑点和手续费建模可配置
- **估时**：3-4 个会话

### WP-2.8 持仓管理与 P&L

- **范围**：`Account` 状态机（cash + positions + transactions）、信号执行模拟器、每日 mark-to-market、P&L 归因。**同一套代码服务于影子账户和（未来的）实施账户**
- **输入**：信号 + 价格数据
- **输出**：`src/portfolio/manager.py` + `src/portfolio/pnl.py`
- **依赖**：WP-0.2, WP-2.5
- **验收**：
  - 完整的开仓/平仓/调仓动作正确
  - mark-to-market 每日运行
  - P&L 归因可分到每只股票、每个策略
- **估时**：2-3 个会话

### WP-2.9 策略生命周期管理器

- **范围**：V0.5 引入。处理活跃 ↔ 归档 ↔ 删除的状态机和回捞流程。包括：归档时的最后业绩快照保存、回捞时的业绩重置、删除时的物理清除
- **输入**：策略对象 + 当前活跃池状态
- **输出**：`src/strategies/lifecycle.py`
- **依赖**：WP-0.2, WP-2.6
- **验收**：
  - 状态转换都有审计日志
  - 内置策略不能被归档/删除（UI 隐藏 + 后端拒绝）
  - 回捞策略业绩重置（影子账户清零，老业绩进归档展示）
- **估时**：1-2 个会话

### WP-2.10 指数跟踪策略（GTAA）

- **范围**：基于 Faber GTAA 的实现。资产池：SPY / QQQ / 2800.HK / 3033.HK / TLT / GLD。规则：每月最后一个交易日检查，价格 > 10 月 SMA 持有，否则换现金/短债。在趋势中的 ETF 等权分配
- **输入**：ETF 价格数据
- **输出**：`src/strategies/index_following.py`
- **依赖**：WP-2.1
- **验收**：
  - 在 2000-2024 数据上跑回测
  - **校准点**：最大回撤显著低于 SPY 同期、年化收益接近 SPY、夏普高于 SPY，符合 Faber 论文核心结论
- **估时**：1-2 个会话

**Phase 2 总验收**：CLI 跑 `python -m bench --strategy <name> --market us --period 2020-2025` 输出该策略在该时段的回测业绩；可创建 custom 策略并跑回测。

---

## Phase 3: 投资助手（4 路并行）

### WP-3.1 Regime 分类器

- **范围**：基于规则的多维度 Regime 分类。输入：宏观数据 + 市场结构数据。输出：`Regime` 对象（含概率分布而非单一标签）。**纯代码，不调用 LLM**
- **输入**：WP-1.3 数据 + WP-1.1/1.2 市场结构
- **输出**：`src/assistant/regime.py`
- **依赖**：Phase 0, WP-1.1, WP-1.2, WP-1.3
- **验收**：
  - 分类规则在历史数据上表现合理（手动校验几个关键转折点：2020-03、2022-10、2024-09）
  - 输出概率分布而非分类标签（避免假精度）
  - 滞回机制（Hysteresis）防止 whipsaw
- **估时**：2-3 个会话

### WP-3.2 资产配置规则引擎

- **范围**：三层配置（现金 vs 股票 / US vs HK / 各市场内策略权重）的规则化决策。输入 Regime + 风险信号，输出 `AssetAllocation` 对象。**纯代码**
- **输入**：Regime 输出
- **输出**：`src/assistant/allocator.py`
- **依赖**：WP-3.1
- **验收**：
  - 三层输出格式符合契约
  - 不同 regime 下输出合理（手动验证 4 个典型 regime）
- **估时**：1-2 个会话

### WP-3.3 策略推荐器

- **范围**：把 Regime → 4 套策略权重的预定义映射表实现成代码，结合当前实施账户和挑战者状态，输出"是否需要重审冠军"的判断
- **输入**：Regime + 当前活跃池状态
- **输出**：`src/assistant/strategy_advisor.py`
- **依赖**：WP-3.1, WP-2.x
- **验收**：
  - 推荐权重和当前权重的对齐度计算正确
  - 偏离阈值触发重审提示
- **估时**：1-2 个会话

### WP-3.4 助手胜率档案

- **范围**：把每次助手输出的判断入库，30/90 天后自动评估"当时的判断对不对"，生成胜率统计、按场景切片的准确率分析
- **输入**：助手历史建议 + 事后市场表现
- **输出**：`src/assistant/track_record.py`
- **依赖**：WP-3.1, WP-3.2, WP-3.3
- **验收**：
  - 每条建议入库，事后定时验证
  - 总分卡 + 切片视图数据正确
- **估时**：1-2 个会话

**Phase 3 总验收**：仪表盘顶部显示当前 Regime；助手简报页能看到推荐资产配置和理由；胜率档案页展示历史建议和事后验证。

---

## Phase 4: 应用层（前后端 2-3 路并行）

### WP-4.1 API 服务

- **范围**：FastAPI 后端，分两套路由。公开路由 `/api/public/*`：策略状态、业绩、当日信号、Regime、助手建议、胜率档案。受保护路由 `/api/private/*`：实施账户、券商配置、自定义策略管理（V0.5+）
- **输入**：核心系统的所有模块
- **输出**：`src/api/main.py` + 各路由模块
- **依赖**：Phase 1-3 部分模块
- **验收**：
  - 所有公开路由返回 200，数据格式符合契约
  - OpenAPI 文档自动生成（`/docs`）
  - JWT 鉴权对受保护路由生效
- **估时**：3-4 个会话

### WP-4.2 主动推送系统

- **范围**：触发规则引擎（Phase 3 的输出 + 阈值规则）、降噪逻辑（冷静期、分级、合并）、多渠道适配器（Email + Telegram + 企业微信，至少接一个）
- **输入**：助手输出 + 事件流
- **输出**：`src/notification/dispatcher.py` + 各渠道 adapter
- **依赖**：WP-3.x
- **验收**：
  - 触发规则按 4 类场景分类正确
  - 冷静期生效（同类推送 24 小时不重复）
  - 至少一条端到端推送可发送（接收方手机/邮箱真收到）
- **估时**：2-3 个会话

### WP-4.3 前端公开仪表盘

- **范围**：未登录用户首屏。包含：当前 Regime 状态卡、4 策略对比卡片、业绩对照曲线、助手最新建议 Feed、胜率档案入口
- **输入**：公开 API
- **输出**：`frontend/src/pages/Dashboard.tsx` 等
- **依赖**：WP-4.1
- **验收**：
  - 浏览器打开看到完整仪表盘
  - 数据实时（每分钟刷新或 WebSocket）
  - 移动端响应式合理
- **估时**：3-4 个会话

### WP-4.4 前端策略管理页

- **范围**：登录用户用。策略库列表、单策略详情（含因子、规则、历史信号）、创建自定义策略对话框（4 维权重滑块）、策略升级/降级工作流
- **输入**：私有 API
- **输出**：`frontend/src/pages/Strategies.tsx` 等
- **依赖**：WP-4.1, V0.5 后端
- **验收**：
  - 创建 custom 策略 → 立即在活跃池可见
  - 升级工作流可执行（含确认 dialog）
  - 历史库展示完整
- **估时**：3 个会话

### WP-4.5 前端持仓与业绩页

- **范围**：登录用户用。实施账户持仓清单、待执行信号、交易记录、累计 P&L 曲线、对标基准
- **输入**：私有 API
- **输出**：`frontend/src/pages/Portfolio.tsx` 等
- **依赖**：WP-4.1, V0.7 后端
- **验收**：
  - 持仓数据实时
  - 待执行信号清晰展示
  - P&L 曲线对标 SPY / HSI 显示
- **估时**：2-3 个会话

---

## Phase 5: 账户与交易系统（独立窗口）

任意时间插入，不阻塞核心开发。

### WP-5.1 用户认证

- **范围**：JWT-based auth，邮箱密码 + 可选 OAuth（Google / GitHub）
- **输出**：`src/auth/`
- **估时**：2 个会话

### WP-5.2 券商凭证安全存储

- **范围**：AES 加密存储 API Key/Secret、密钥管理
- **输出**：`src/auth/credentials.py`
- **估时**：1-2 个会话

### WP-5.3 券商 API 适配器

- **范围**：第一期建议先做 IBKR（盈透）的 Python API 接入，后续可加富途、雪盈等
- **输出**：`src/brokers/ibkr.py`
- **估时**：3-4 个会话

### WP-5.4 自动 / 手动执行模式

- **范围**：两套执行后端，前者自动下单后者推送通知，可配置切换
- **输出**：`src/execution/`
- **估时**：2 个会话

---

## 关键接口契约（节选）

详见独立的 `CONTRACTS.md`，这里列最关键的几个：

### Strategy 接口

```python
class StrategyBase(ABC):
    name: str
    type: StrategyType  # BUILT_IN | CUSTOM
    parameters: StrategyParameters

    @abstractmethod
    def screen(self, universe: list[Stock], date: date) -> list[Stock]: ...

    @abstractmethod
    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]: ...

    @abstractmethod
    def exit_rules(self, position: Position, date: date) -> ExitDecision: ...

    @abstractmethod
    def get_score(self, stock: Stock, date: date) -> float: ...
```

### LLM Service 契约

```python
class LLMGateway:
    async def complete(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.0,
    ) -> BaseModel: ...
```

### Signal 契约

```python
class Signal(BaseModel):
    stock_code: str
    direction: Literal["BUY", "SELL", "HOLD"]
    buy_range: tuple[float, float] | None
    stop_loss: float | None
    take_profit: float | None
    position_size_pct: float
    confidence: float  # 0-1
    reason_code: str
    reason_narrative: str | None
    generated_at: datetime
    strategy_id: str
```

---

## 修订历史

| 日期 | 版本 | 修订内容 |
|------|------|----------|
| 初始 | v1.0 | 35 个 WP 完整定义 |
