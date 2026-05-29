# 竞品分析多Agent协作系统 - 技术设计文档

> 项目目标：60进10竞赛获奖，评分维度驱动的架构设计
> 开发周期：3周（2026.05.21 - 2026.06.11）
> 开发人员：1人
> 演示场景：项目管理SaaS（Notion vs Feishu vs ClickUp）

---

## 一、评分维度拆解与应对策略

### 1.1 多Agent协作与输出可信度（35%）—— 决胜维度

**评委关注点：**
- 角色划分清晰，职责边界明确无重叠
- LangGraph DAG任务流转可视化、可追溯
- Agent间采用结构化消息传递（function calling / 标准Schema），非纯自然语言对话
- 反馈闭环真实可触发：质检Agent能识别问题并打回，重做后输出有改善（非伪闭环）
- 输出严格符合预定义竞品知识Schema，字段完整、格式一致
- 信息溯源完整：每条结论可定位到原始数据源，支持一键跳转或溯源查看

**实现策略：**

| 要求 | 实现方案 | 验收标准 |
|------|----------|----------|
| 角色划分 | 4个Agent：Collector/Analyst/Writer/QA，每个有独立prompt+工具集+输出Schema | 任意两个Agent的工具集零交集 |
| DAG可视化 | LangGraph StateGraph + 前端react-flow渲染 | 答辩时实时展示节点流转状态 |
| 结构化消息 | AgentMessage Pydantic模型，function_name + arguments格式 | 所有Agent间通信可JSON序列化回放 |
| 反馈闭环 | QA Agent输出QAFeedback，含issues列表+verdict(pass/revise) | 演示一个完整的"打回→修正→分数提升"case |
| Schema合规 | Pydantic强校验 + Claude structured output，校验失败自动重试(max 3次) | 最终输出100%通过Schema校验 |
| 信息溯源 | EvidencedClaim模型，每条结论带source_url + snippet + snapshot_hash | 前端点击结论可展开证据链 |

**答辩演示重点：**
- 准备一个"QA发现Collector漏采了ClickUp的AI功能数据→打回→Collector补采→Analyst重新分析→报告更新"的完整case
- 展示AgentMessage的JSON流转日志，证明非自然语言对话

---

### 1.2 技术深度与工程完整度（25%）

**评委关注点：**
- 端到端链路完整：数据采集→Agent编排→知识存储→后端接口→前端交互，可支持现场演示
- 可观测性达标：每个Agent的Prompt、输入、输出、决策过程、Token消耗均有日志/Trace可查
- 上下文管理、幻觉抑制策略（自一致性校验、引用强制、超长上下文分片）
- 系统稳定性：异常处理、超时重试、降级机制完备，演示过程无明显卡顿或崩溃
- 技术方案有独特或前瞻性思考（自适应任务拆分、Agent自评估、动态Schema演化）

**实现策略：**

| 要求 | 实现方案 | 验收标准 |
|------|----------|----------|
| 端到端链路 | FastAPI后端 + HTMX前端 + LangGraph编排 + PostgreSQL持久化 | 从输入竞品名到输出报告全程无人工干预 |
| 可观测性 | Langfuse本地Docker部署，@observe装饰器包裹所有Agent调用 | 打开Langfuse dashboard可查看完整trace树 |
| 幻觉抑制 | 三重机制：引用强制(无source则拒绝输出) + QA事实核查 + 自一致性校验 | 最终报告每条结论都有≥1个source |
| 系统稳定性 | 重试3次 + 指数退避 + Redis缓存中间结果 + 超时降级 | 演示时Claude API偶发超时不会导致整体崩溃 |
| 技术亮点 | 行业模板热插拔 + Agent置信度自评估 + 增量更新机制 | 答辩时切换行业模板实时演示 |

**幻觉抑制三重机制详解：**
```
第一重 - 引用强制（Collector层）：
  Collector输出的每条数据必须包含source_url和原文snippet
  无法提供来源的信息直接丢弃，不进入后续流程

第二重 - 自一致性校验（Analyst层）：
  对同一事实从多个source交叉验证
  置信度 = 一致source数 / 总source数
  confidence < 0.5 的claim标记为"待验证"

第三重 - 事实核查（QA层）：
  随机抽取20%的claim回溯原始URL验证
  发现不一致则触发反馈闭环
```

---

### 1.3 业务价值与产品体验（20%）

**评委关注点：**
- 相比传统人工竞品分析，在效率(时间)、覆盖度(信息源)、一致性(结构化)上有可量化的提升
- 产品形态贴合企业竞品分析真实工作流，具备可落地性与可扩展性（可换行业、可换竞品对象）
- 交互设计流畅：报告查看、溯源跳转、人工介入修正、Agent决策回放等核心动作易用直观
- 设计了清晰的业务闭环（含关键指标如准确率、覆盖率、人工修正率），支持后续运营迭代

**实现策略：**

| 要求 | 实现方案 | 验收标准 |
|------|----------|----------|
| 效率提升 | 准备对比数据：人工分析1个竞品约8小时，系统15-20分钟 | 答辩时展示时间对比图 |
| 可扩展性 | 行业模板热插拔(SaaS/消费品/硬件)，输入竞品名即可运行 | 现场换一个行业演示 |
| 交互设计 | 报告页支持：结论点击展开证据链、DAG流程回放、人工标注修正 | 评委可现场操作 |
| 业务指标 | 自动计算：Schema填充率、溯源覆盖率、QA通过率、人工修正率 | 报告末尾附带质量评分卡 |

**量化指标设计：**
```
- Schema填充率 = 已填字段数 / 总字段数（含必填+选填）
- 溯源覆盖率 = 有source的claim数 / 总claim数（目标≥95%）
- QA首次通过率 = 首次QA pass的任务数 / 总任务数
- 人工修正率 = 人工介入修改的字段数 / 总字段数（越低越好）
- 信息源覆盖度 = 实际采集的source类型数 / 预定义source类型数
```

---

### 1.4 代码质量与文档（10%）

**评委关注点：**
- 代码风格规范、模块化清晰、关键逻辑注释充分、可读性高
- 项目文档齐全：README、架构图、Agent角色与协议文档、部署说明
- Git提交记录规范，分支管理清晰
- TRAE等AI编程工具的使用痕迹清晰，体现深度协作

**实现策略：**
- 代码规范：ruff format + ruff check，pre-commit hook强制执行
- Git规范：conventional commits（feat/fix/docs/refactor前缀）
- 文档：README.md + docs/目录（架构图用mermaid）
- TRAE痕迹：开发过程中保留Trae的对话截图和生成记录

---

### 1.5 合规、材料与答辩（10%）

**评委关注点：**
- 信息采集合规：遵守目标站点robots.txt与服务条款，对外部数据来源有明确授权或公开声明
- 数据隐私与安全：用户访谈、问卷数据脱敏处理，无敏感信息泄露
- 工具、模型、数据的使用符合公司及挑战赛"工具与资源使用规范"
- 提交材料完整：方案文档、演示视频、代码库齐全规范
- 答辩讲解清晰有条理，演示直观，问答应对得当

**实现策略：**
- 爬虫加robots.txt检查，不合规的URL跳过并记录
- 所有采集数据标注来源类型（公开/授权/用户生成）
- 问卷/访谈数据自动脱敏（正则替换手机号、邮箱等PII）
- 准备3-5分钟演示视频 + 方案PPT + 完整代码库

---

## 二、系统架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (HTMX + Jinja2)                  │
│  ┌──────────┐  ┌──────────────┐  ┌───────────┐  ┌───────────┐  │
│  │报告查看器 │  │DAG流程可视化  │  │溯源面板    │  │人工修正    │  │
│  └──────────┘  └──────────────┘  └───────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │ HTTP
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │Tasks API │  │Reports   │  │Traces    │  │Feedback API    │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                  LangGraph Orchestrator                           │
│                                                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │load_     │───▶│Collector │───▶│Analyst   │───▶│Writer    │  │
│  │template  │    │Agent     │    │Agent     │    │Agent     │  │
│  └──────────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘  │
│                       ▲               ▲               ▲         │
│                       │   ┌───────────┴───────────────┘         │
│                       │   │                                      │
│                       └───┤  ┌──────────┐                       │
│                           └──│QA Agent  │ (条件路由：pass/revise)│
│                              └──────────┘                       │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     Infrastructure                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │PostgreSQL│  │Qdrant    │  │Redis     │  │Langfuse        │  │
│  │(持久化)  │  │(规划中)   │  │(缓存/队列)│  │(可观测性)      │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     External Services                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────────┐  │
│  │Claude API│  │Jina      │  │Playwright (仅JS渲染页面)      │  │
│  │(LLM)    │  │Reader    │  │                               │  │
│  └──────────┘  └──────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 DAG任务流转详细设计

```
                    ┌─────────────┐
                    │  START      │
                    │ (用户输入)   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │load_template│  根据industry字段选择行业模板
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Collector  │  并行采集多个竞品的公开信息
                    │  Agent      │  输出：raw_data per competitor
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Analyst    │  结构化分析：功能树/定价/SWOT
                    │  Agent      │  输出：CompetitorProfile per competitor
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Writer     │  生成结构化竞品报告
                    │  Agent      │  输出：report_draft (Markdown)
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
              ┌─────│  QA Agent   │─────┐
              │     └─────────────┘     │
              │                         │
         verdict=pass            verdict=revise_*
              │                         │
              ▼                         ▼
        ┌──────────┐          ┌──────────────────┐
        │   END    │          │ 路由到对应Agent   │
        │ 输出报告  │          │ iteration += 1   │
        └──────────┘          │ (max 3次)        │
                              └──────────────────┘
```

### 2.3 Agent角色定义

| Agent | 职责 | 输入 | 输出 | 工具集 |
|-------|------|------|------|--------|
| Collector | 公开信息采集 | CollectRequest(target, scope) | 结构化原始数据 + SourceReference列表 | Jina Reader, Playwright, 网页快照 |
| Analyst | 结构化分析 | 原始数据 + CompetitorProfile Schema | 填充完整的CompetitorProfile | claims 聚合, 来源映射, 完整度评分 |
| Writer | 报告撰写 | CompetitorProfile列表 + 报告模板 | Markdown格式竞品报告 | 模板引擎, 图表生成 |
| QA | 质量检验 | 前序Agent的所有输出 | QAFeedback(verdict + issues) | Schema校验器, URL可达性检查, 事实核查 |

### 2.4 行业模板热插拔机制

```
templates/
├── saas.py          # SaaS产品模板（API开放度、集成数量、协作特性、AI功能）
├── consumer.py      # 消费品模板（渠道分布、品牌舆情、市场份额、供应链）
└── hardware.py      # 硬件产品模板（参数对比、生态锁定、可维修性、认证）

加载流程：
1. 用户输入 industry="saas"
2. Orchestrator.load_template 节点从 TEMPLATE_REGISTRY 获取模板
3. 模板字段注入到 CompetitorProfile.extensions
4. 后续Agent按扩展后的Schema工作
5. QA Agent校验时同时检查基础字段和扩展字段
```

---

## 三、核心数据结构设计

### 3.1 CompetitorProfile Schema（竞品档案）

```python
class CompetitorProfile(BaseModel):
    """竞品档案主Schema - 所有Agent的共同产出目标"""

    # ---- 基础信息 ----
    company_name: str
    product_name: str
    website: str
    industry: str
    founded_year: int | None = None
    funding_stage: str | None = None

    # ---- 结构化分析（核心） ----
    feature_tree: list[FeatureNode] = []        # 功能树（层级结构）
    pricing: PricingModel | None = None          # 定价模型
    user_personas: list[UserPersona] = []        # 用户画像
    swot: list[SWOTItem] = []                    # SWOT分析

    # ---- 动态扩展（行业模板注入） ----
    extensions: dict[str, Any] = {}
    # 运行时由Orchestrator根据行业模板填充
    # SaaS示例: {"api_openness": EvidencedClaim(...), "integration_count": 150}

    # ---- 元数据 ----
    schema_version: str = "1.0"
    created_at: datetime
    last_updated: datetime
    completeness_score: float  # 自动计算：已填字段/总字段
```

**关键设计：EvidencedClaim（溯源原子单元）**

```python
class EvidencedClaim(BaseModel):
    """每条分析结论必须携带的溯源信息"""
    claim: str                          # 结论文本
    confidence: float                   # 置信度 0-1
    sources: list[SourceReference]      # 至少1个来源（强制）
    reasoning: str                      # 推理过程
    verified_by: str | None = None      # QA验证标记
    verified_at: datetime | None = None

class SourceReference(BaseModel):
    """数据来源"""
    source_type: SourceType             # web_page/app_store_review/official_doc/...
    url: str | None = None
    title: str
    snippet: str                        # 原文摘录（核心溯源依据）
    accessed_at: datetime
    snapshot_hash: str | None = None    # 网页快照hash，防止源头篡改后无法验证
```

### 3.2 Agent间通信消息格式

```python
class AgentMessage(BaseModel):
    """Agent间通信标准格式 - function calling风格"""

    # 路由信息
    message_id: str
    trace_id: str                       # 关联Langfuse trace
    message_type: MessageType           # task_assign/task_result/feedback/revision
    from_agent: str                     # collector/analyst/writer/qa
    to_agent: str
    timestamp: datetime

    # function calling载荷（核心）
    function_name: str                  # 要求目标Agent执行的操作名
    arguments: dict[str, Any]           # 操作参数（对应各Request模型）

    # 上下文
    context: MessageContext
    priority: int = 0

    # 溯源链
    parent_message_id: str | None       # 上游消息ID（构成消息链）
    retry_of: str | None                # 如果是重试，指向原始消息

class MessageContext(BaseModel):
    """消息上下文"""
    competitor_name: str | None
    schema_version: str = "1.0"
    iteration: int = 1                  # 当前迭代轮次
    max_iterations: int = 3             # 最大迭代次数
    constraints: list[str] = []         # 约束条件
    previous_feedback: list[str] = []   # 历史反馈摘要（避免重复犯错）
```

**预定义操作（function calling）：**

| function_name | 发起方 | 目标方 | arguments模型 |
|---------------|--------|--------|---------------|
| collect_competitor_data | Orchestrator | Collector | CollectRequest |
| analyze_competitor | Orchestrator | Analyst | AnalyzeRequest |
| write_report | Orchestrator | Writer | WriteRequest |
| review_output | Orchestrator | QA | 前序Agent的完整输出 |
| revise_with_feedback | QA | Collector/Analyst/Writer | QAFeedback |
| report_error | Any | Orchestrator | {error, original_task} |

### 3.3 Trace/Span可观测性模型

```python
class TraceSpan(BaseModel):
    """对齐Langfuse数据模型的追踪记录"""

    trace_id: str                       # 顶层任务ID
    span_id: str                        # 当前操作ID
    parent_span_id: str | None          # 父操作（构成树形结构）
    name: str                           # 操作名称
    kind: SpanKind                      # agent_invocation/llm_call/tool_call/validation/feedback_loop
    agent_role: str                     # 哪个Agent产生的

    # 时间
    start_time: datetime
    end_time: datetime | None
    duration_ms: int | None

    # IO（完整记录，支持回放）
    input_data: dict[str, Any]
    output_data: dict[str, Any]

    # LLM调用详情
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_cost_usd: float | None

    # 状态
    status: str                         # running/completed/failed/retried
    error: str | None
    retry_count: int = 0

class FeedbackRecord(BaseModel):
    """反馈闭环记录 - 证明闭环真实有效的关键证据"""
    feedback_id: str
    from_agent: str                     # 通常是qa
    to_agent: str                       # 被打回的agent
    issue_type: str                     # missing_source/low_confidence/schema_violation/factual_error
    issue_description: str
    original_content: dict              # 修正前的内容
    revised_content: dict | None        # 修正后的内容
    improvement_score: float | None     # 前后质量对比分（量化改善）
    resolved: bool
    created_at: datetime
    resolved_at: datetime | None
```

---

## 四、技术选型确认

| 组件 | 选型 | 理由 |
|------|------|------|
| Agent编排 | LangGraph | 原生支持条件路由、状态管理、DAG定义，比CrewAI更灵活 |
| 大模型 | Claude API (Sonnet 4.6) | 结构化输出能力强，tool use原生支持，成本可控 |
| 爬虫（主力） | Jina Reader | 一行URL获取clean markdown，开发成本极低 |
| 爬虫（补充） | Playwright | 仅用于JS渲染页面（SaaS定价页等） |
| 可观测性 | Langfuse (Docker本地) | 开源免费，trace/span/generation原生支持，UI开箱即用 |
| 结构化输出 | Pydantic v2 | Schema定义+校验一体，与Claude structured output无缝配合 |
| 向量库 | Qdrant (规划中) | 轻量、性能好、Python SDK友好；用于后续 RAG 增强，当前版本未启用 |
| 数据库 | PostgreSQL | 竞品档案持久化，JSON字段支持extensions |
| 缓存/队列 | Redis | 中间结果缓存 + 去重 + 简单任务队列 |
| 后端 | FastAPI | 异步原生、自动文档、Pydantic深度集成 |
| 前端 | HTMX + Jinja2 | 开发速度快，无需前端构建工具，一人开发友好 |
| DAG可视化 | react-flow (CDN) | 单页引入，渲染LangGraph的节点和边 |
| 包管理 | uv | 速度快，lockfile确定性好 |
| 代码规范 | ruff | format + lint一体，零配置 |

---

## 五、项目目录结构

```
competitive-analysis-agents/
├── README.md                          # 项目说明（评分项）
├── pyproject.toml                     # 依赖管理
├── docker-compose.yml                 # 基础设施一键启动
├── .env.example                       # 环境变量模板
├── Makefile                           # 常用命令
├── ruff.toml                          # 代码规范配置
│
├── docs/
│   ├── architecture.md                # 架构设计（含mermaid图）
│   ├── agent-roles.md                 # Agent角色与协议
│   ├── api-spec.md                    # API接口文档
│   ├── deployment.md                  # 部署说明
│   └── demo-script.md                # 答辩演示脚本
│
├── src/
│   ├── __init__.py
│   ├── schemas/                       # 数据结构定义（零外部依赖）
│   │   ├── __init__.py
│   │   ├── competitor.py              # CompetitorProfile + FeatureNode + PricingModel
│   │   ├── message.py                # AgentMessage + 各种Request/Response
│   │   ├── trace.py                  # TraceSpan + FeedbackRecord
│   │   └── extensions.py            # IndustryTemplate + TEMPLATE_REGISTRY
│   │
│   ├── agents/                        # Agent实现
│   │   ├── __init__.py
│   │   ├── base.py                    # BaseAgent（Langfuse集成、消息收发）
│   │   ├── collector/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py               # CollectorAgent
│   │   │   ├── tools.py              # jina_read() + playwright_scrape()
│   │   │   └── prompts.py            # 采集专用prompt
│   │   ├── analyst/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py               # AnalystAgent
│   │   │   ├── tools.py              # compare_features() + generate_swot()
│   │   │   └── prompts.py
│   │   ├── writer/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py               # WriterAgent
│   │   │   ├── templates.py          # 报告Markdown模板
│   │   │   └── prompts.py
│   │   └── qa/
│   │       ├── __init__.py
│   │       ├── agent.py               # QAAgent（反馈闭环核心）
│   │       ├── validators.py         # schema_validate() + fact_check() + source_verify()
│   │       └── prompts.py
│   │
│   ├── orchestrator/                  # LangGraph编排
│   │   ├── __init__.py
│   │   ├── graph.py                   # StateGraph定义（DAG核心）
│   │   ├── state.py                   # AnalysisState（全局共享状态）
│   │   ├── nodes.py                   # 各节点函数
│   │   ├── edges.py                   # 条件路由（qa_router）
│   │   └── callbacks.py              # Langfuse回调
│   │
│   ├── storage/                       # 存储层
│   │   ├── __init__.py
│   │   ├── postgres.py               # 竞品档案CRUD
│   │   ├── vector.py                 # Qdrant语义检索（规划中，未实现）
│   │   ├── cache.py                  # Redis缓存
│   │   └── snapshot.py              # 网页快照存储（溯源用）
│   │
│   ├── observability/                 # 可观测性
│   │   ├── __init__.py
│   │   ├── langfuse_client.py        # Langfuse初始化与封装
│   │   ├── decorators.py            # @trace_agent @trace_llm @trace_tool
│   │   └── metrics.py               # 业务指标计算
│   │
│   ├── api/                           # FastAPI后端
│   │   ├── __init__.py
│   │   ├── main.py                    # app入口 + 中间件
│   │   ├── routes/
│   │   │   ├── tasks.py              # POST /tasks, GET /tasks/{id}
│   │   │   ├── reports.py           # GET /reports/{id}, GET /reports/{id}/export
│   │   │   ├── traces.py           # GET /traces/{id}, GET /traces/{id}/spans
│   │   │   └── feedback.py         # POST /feedback（人工介入）
│   │   └── deps.py                   # 依赖注入
│   │
│   └── config/
│       ├── __init__.py
│       └── settings.py               # Pydantic Settings
│
├── templates/                         # Jinja2 HTML模板
│   ├── base.html                      # 布局
│   ├── index.html                     # 首页（任务创建）
│   ├── report.html                    # 报告查看（含溯源面板）
│   ├── trace.html                     # Trace时间线
│   └── dag.html                       # DAG可视化（引入react-flow CDN）
│
├── static/
│   ├── styles.css
│   └── dag-renderer.js               # react-flow初始化脚本
│
├── tests/
│   ├── unit/
│   │   ├── test_schemas.py
│   │   ├── test_collector.py
│   │   ├── test_analyst.py
│   │   └── test_qa_validators.py
│   └── integration/
│       ├── test_feedback_loop.py     # 反馈闭环端到端测试
│       └── test_full_pipeline.py
│
└── scripts/
    ├── seed_demo.py                   # 演示数据初始化
    ├── run_analysis.py               # CLI入口
    └── export_report.py             # 导出PDF/Markdown
```

---

## 六、开发进度安排（3周21天）

### 第一周：基础设施 + Agent单体开发

| 日期 | 天数 | 任务 | 产出物 | 验收标准 |
|------|------|------|--------|----------|
| D1 | 1 | 项目初始化 + docker-compose | 基础设施全部跑通 | PostgreSQL/Redis/Qdrant/Langfuse均可访问 |
| D2 | 1 | schemas/全部定义完成 | 4个schema文件 | Pydantic模型可实例化，单元测试通过 |
| D3 | 1 | BaseAgent + Langfuse装饰器 | base.py + observability/ | 调用一次LLM能在Langfuse看到trace |
| D4-D5 | 2 | CollectorAgent完整实现 | collector/ + tools.py | 输入"Notion"能返回结构化数据+source |
| D6 | 1 | AnalystAgent实现 | analyst/ | 输入raw data能输出CompetitorProfile |
| D7 | 1 | WriterAgent + QAAgent实现 | writer/ + qa/ | 各Agent独立可运行 |

**第一周里程碑：4个Agent各自独立工作，Langfuse可查看每个Agent的trace。**

### 第二周：编排联调 + 后端API

| 日期 | 天数 | 任务 | 产出物 | 验收标准 |
|------|------|------|--------|----------|
| D8-D9 | 2 | LangGraph编排（graph/state/nodes/edges） | orchestrator/ | DAG跑通：输入竞品名→输出报告 |
| D10 | 1 | 反馈闭环调试 | QA打回逻辑 | 能触发至少一次打回→修正→通过 |
| D11-D12 | 2 | FastAPI后端全部接口 | api/ | Swagger文档可访问，接口可调用 |
| D13 | 1 | 存储层完善（PostgreSQL持久化 + Qdrant索引） | storage/ | 分析结果持久化，重启不丢失 |
| D14 | 1 | 端到端集成测试 | tests/integration/ | 完整流程跑通无报错 |

**第二周里程碑：完整pipeline可运行，从输入到报告输出全自动，反馈闭环可触发。**

### 第三周：前端 + 打磨 + 答辩准备

| 日期 | 天数 | 任务 | 产出物 | 验收标准 |
|------|------|------|--------|----------|
| D15-D16 | 2 | 前端页面（报告查看+溯源面板+DAG可视化） | templates/ + static/ | 浏览器可操作，溯源点击可跳转 |
| D17 | 1 | 人工介入修正功能 + 业务指标面板 | feedback接口 + metrics | 可手动修正字段，指标自动计算 |
| D18 | 1 | 演示数据准备（Notion vs Feishu vs ClickUp完整跑一遍） | seed数据 | 有一份完整的高质量演示报告 |
| D19 | 1 | 文档补全（README/架构图/部署说明） | docs/ | 文档齐全，新人可按文档部署 |
| D20 | 1 | 演示视频录制 + 答辩PPT | video + ppt | 3-5分钟视频，流畅无卡顿 |
| D21 | 1 | 答辩彩排 + 边界case处理 | 稳定版本 | 模拟评委提问，准备应答 |

**第三周里程碑：产品形态完整，演示流畅，材料齐全。**

---

## 七、关键风险与注意事项

### 7.1 按评分维度的风险清单

#### 多Agent协作（35%）相关风险

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 反馈闭环变成"假闭环"（QA永远pass） | 致命，评委一眼看穿 | QA prompt设计要严格，故意设置高标准；准备一个必定触发打回的demo case |
| Agent间消息退化为自然语言 | 丢分 | 强制所有通信走AgentMessage模型，日志中可展示JSON格式 |
| Schema校验形同虚设 | 丢分 | Pydantic strict mode + 校验失败自动重试，不能跳过 |
| 溯源链断裂（某些claim无source） | 丢分 | Collector层强制：无source的信息不输出；QA层二次检查 |

**最重要的一点：答辩时必须演示一个完整的反馈闭环case。建议提前设计好这个case的触发条件。**

#### 技术深度（25%）相关风险

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| Langfuse部署失败或数据丢失 | 可观测性无法展示 | 提前测试Docker部署，准备截图备份 |
| Claude API超时导致演示卡顿 | 稳定性扣分 | Redis缓存中间结果 + 超时降级（返回缓存版本） |
| 上下文超长导致LLM输出质量下降 | 幻觉增多 | 分片处理：单次输入不超过8000 tokens，超长内容分批 |
| 演示时网络不稳定 | 崩溃 | 准备离线演示方案：预跑结果存入DB，前端展示已有数据 |

#### 业务价值（20%）相关风险

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 报告质量不如人工 | 业务价值存疑 | 重点打磨Writer prompt + 多轮迭代；强调效率优势而非质量替代 |
| 行业模板切换时出bug | 可扩展性存疑 | 三套模板都提前跑通测试，答辩只演示最稳定的SaaS |
| 缺少量化对比数据 | 说服力不足 | 提前准备：人工耗时统计 vs 系统耗时，信息覆盖度对比 |

#### 代码与文档（10%）相关风险

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 最后一周赶工导致代码混乱 | 扣分 | 从D1开始用ruff，pre-commit hook强制 |
| Git历史混乱 | 扣分 | conventional commits，每个功能一个分支 |
| 文档缺失 | 扣分 | D19专门留一天补文档，不能省 |

### 7.2 技术实现注意事项

**Claude API使用：**
```
- 使用 claude-sonnet-4-6 作为主力模型（性价比最优）
- 关键分析环节（SWOT生成、报告撰写）可用 claude-opus-4-7（质量更高）
- 所有调用启用 prompt caching（system prompt缓存，节省成本）
- structured output 用 tool_use 模式强制JSON输出
- 设置合理的 max_tokens：采集4096，分析8192，报告16384
```

**Langfuse集成要点：**
```
- 每个Agent.execute()调用创建一个span
- 每次LLM调用创建一个generation（自动记录token/cost）
- 反馈闭环创建专门的feedback_loop span
- trace_id贯穿整个任务生命周期
- 前端trace页面直接链接到Langfuse dashboard
```

**反馈闭环设计要点：**
```
- QA Agent的判定标准要明确且可解释：
  1. Schema完整性检查（字段缺失→revise_collect）
  2. 溯源完整性检查（claim无source→revise_collect）
  3. 逻辑一致性检查（SWOT矛盾→revise_analyze）
  4. 报告质量检查（结构混乱/信息遗漏→revise_write）
- 每次打回必须携带具体的issue描述和修改建议
- 修正后必须记录improvement_score（前后对比）
- max_iterations=3，防止死循环
```

**爬虫合规：**
```
- 每次请求前检查robots.txt
- 请求间隔≥2秒（避免被封）
- User-Agent标明是研究用途
- 不爬登录后内容，只采集公开页面
- 保存网页快照hash用于溯源验证
```

### 7.3 答辩准备要点

**必须准备的演示场景：**
1. 完整流程演示：输入"Notion vs Feishu vs ClickUp" → 自动跑完 → 展示报告
2. 反馈闭环演示：展示QA打回→修正→改善的完整过程
3. 溯源演示：点击报告中某条结论 → 展开证据链 → 跳转原始URL
4. 可观测性演示：打开Langfuse dashboard → 展示trace树 → 查看token消耗
5. 行业切换演示：切换到消费品模板 → 展示Schema变化

**评委可能问的问题：**
- "如果Claude API挂了怎么办？" → 降级策略：返回缓存结果 + 标记为"待更新"
- "如何保证信息的时效性？" → 每条数据标记accessed_at，超过7天自动标记为"可能过期"
- "Agent之间为什么不用自然语言通信？" → 结构化消息可校验、可回放、可审计，自然语言有歧义
- "和直接用ChatGPT有什么区别？" → 多Agent协作+Schema强制+溯源+反馈闭环，单LLM做不到
- "怎么评估系统输出的准确性？" → QA Agent事实核查 + 人工抽检 + 溯源覆盖率指标

### 7.4 开发优先级决策原则

```
优先级排序（当时间冲突时）：

1. 反馈闭环能跑通（35%权重的核心得分点）
2. Langfuse trace可展示（25%权重的核心得分点）
3. 端到端流程无报错（演示基础）
4. 溯源链完整（35%权重的得分点）
5. 前端可操作（20%权重）
6. 文档齐全（10%权重）
7. 行业模板切换（加分项）
8. 业务指标面板（加分项）

如果第二周结束时还有bug：
- 优先修反馈闭环相关的bug
- 前端可以简化（纯JSON展示也行，不影响核心得分）
- 文档最后一天集中补
```

---

## 八、技术亮点（拉开差距的点）

### 8.1 Agent置信度自评估

每个Agent输出时自带confidence score，QA Agent根据置信度决定审查深度：
- confidence > 0.8：抽检20%的claim
- confidence 0.5-0.8：全量检查
- confidence < 0.5：直接打回要求补充数据

### 8.2 增量更新机制

第二次分析同一竞品时，只采集有变化的部分（通过snapshot_hash对比），大幅提升效率。答辩时可演示："上周分析过Notion，本周只更新了定价页变化"。

### 8.3 对比矩阵自动生成

Analyst Agent自动生成多竞品对比矩阵（feature × competitor），支持前端表格渲染，一目了然。

### 8.4 决策回放

前端支持"回放"某个Agent的决策过程：按时间线展示每一步的输入→思考→输出，评委可以看到Agent是如何一步步得出结论的。

---

## 九、依赖清单

```toml
# pyproject.toml 核心依赖
[project]
dependencies = [
    "langgraph>=0.2",
    "langchain-anthropic>=0.3",
    "anthropic>=0.40",
    "langfuse>=2.50",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "httpx>=0.27",
    "jinja2>=3.1",
    "sqlalchemy>=2.0",
    "asyncpg>=0.30",
    "redis>=5.0",
    "playwright>=1.48",
    "python-multipart>=0.0.12",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "pre-commit>=4.0",
]
```

---

## 十、Docker Compose 服务清单

```yaml
services:
  postgres:     # 端口 5432，竞品档案+任务记录持久化
  redis:        # 端口 6379，缓存+简单队列
  langfuse-db:  # Langfuse专用PostgreSQL
  langfuse:     # 端口 3000，可观测性dashboard
```

一键启动：`docker compose up -d`，所有基础设施就绪。

---

*文档版本：v1.0 | 创建日期：2026-05-21 | 最后更新：2026-05-21*
