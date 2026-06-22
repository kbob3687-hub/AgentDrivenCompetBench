import type { SSEEvent, SSEComplete, SSEQaVerdict } from './types'

export interface DemoEvent {
  /** 距离上一个事件的延迟（毫秒） */
  delay: number
  event: SSEEvent
}

const REPORT_MD = `# Notion 竞品分析报告

> 分析对象：**Notion** | 行业：**SaaS / 项目管理** | 生成时间：2026-06-15

---

## 一、执行摘要

Notion 是目前综合能力最强的 all-in-one 工作空间产品，以"块编辑器 + 数据库 + AI"三位一体的架构覆盖笔记、知识库、项目管理、团队协作四大场景。相比飞书和 ClickUp，Notion 的核心护城河在于**模板市场生态**（20000+ 模板）和**社区驱动的增长飞轮**，但其在企业级安全合规和移动端体验方面存在明显短板。[1]

| 维度 | 评分 | 竞争力 |
|------|------|--------|
| 核心功能 | ★★★★☆ | 强大但分散 |
| 集成生态 | ★★★☆☆ | 数量不足，深度一般 |
| AI 能力 | ★★★★☆ | Notion AI 领先 |
| 移动体验 | ★★☆☆☆ | 明显短板 |
| 定价策略 | ★★★☆☆ | 个人友好，企业偏贵 |
| 安全合规 | ★★★☆☆ | SOC 2 但缺 FedRAMP |

---

## 二、核心功能分析

### 2.1 块编辑器

Notion 的基础编辑单元是"块"（Block），支持 50+ 块类型，包括文本、表格、看板、日历、画廊、代码等。这种统一抽象使得用户可以在同一页面内混合使用多种视图，无需在不同工具间切换。[2]

### 2.2 数据库

Notion 数据库可视作轻量级 Airtable，支持筛选、排序、分组、公式、关联等操作。但以下限制值得关注：[3]
- 单数据库上限 100,000 行（企业版）
- 公式语言较弱（无变量、无自定义函数）
- 缺少真正的数据验证规则

### 2.3 协作功能

支持实时协同编辑、评论、@提醒、页面分享。2025 年新增"协同光标"功能后体验明显改善，但仍缺少视频通话和白板等深度协作能力。[4]

---

## 三、集成与 API

### 3.1 第三方集成

官方列出约 100 个集成 [5]，显著低于飞书的 500+。关键集成包括 Slack、GitHub、Google Calendar、Figma、Jira。缺少 Salesforce、Zendesk 等企业级集成。

### 3.2 Notion API

2021 年正式发布，RESTful 风格，支持 CRUD 操作。OAuth 2.0 认证，速率限制为每秒 3 次请求。[6] 对开发者友好的点：详细的 SDK（JS/TS/Python）、Webhook 支持。不足之处：批量操作支持差、无 GraphQL、不支持实时订阅。

### 3.3 数据导出

支持 Markdown + CSV 导出，但不支持批量导出工作区，无原生备份 API。[7]

---

## 四、AI 能力

Notion AI 于 2023 年上线，核心能力：[8]
- **写作辅助**：续写、改写、翻译、摘要
- **Q&A**：对工作空间内容进行自然语言问答
- **自动填充**：数据库行列智能补全

2026 年新增"AI Agent"功能，支持自动化工作流触发。每位成员 $10/月的附加费，对比飞书 AI（免费集成），定价明显偏高。

---

## 五、定价策略

| 层级 | 月费/成员 | 核心差异 |
|------|-----------|----------|
| Free | $0 | 10 个 guest，7 天历史 |
| Plus | $10 | 无限文件上传，30 天历史 |
| Business | $18 | 私有团队空间，90 天历史，SAML SSO |
| Enterprise | 议价 | 高级安全，审计日志，无限历史 |

Notion 的个人免费版相当慷慨，但企业版定价在美国市场偏高（对比 ClickUp Business $12/成员）。[9]

---

## 六、用户画像

核心用户群体：[10]
1. **个人知识工作者**（40%）：笔记、个人 Wiki、任务管理
2. **创业团队**（30%）：轻量项目管理 + 文档协作
3. **中型企业**（20%）：跨部门知识库、项目追踪
4. **教育领域**（10%）：学生笔记、课程管理（有教育优惠）

---

## 七、SWOT 分析

### 优势
- 块编辑器 + 数据库 + AI 独特组合
- 20000+ 模板生态和社区驱动增长 [1]
- 极低的个人用户获取成本（免费版转化）

### 劣势
- 移动端体验明显劣于桌面端
- 企业安全合规覆盖不足（仅 SOC 2）
- 离线支持差（仅部分缓存）

### 机会
- AI Agent 自动化工作流是下一个增长引擎
- 垂直行业模板（法律、医疗）可拓展 TAM
- 中国市场可通过 Lark/飞书合作切入

### 威胁
- 飞书在团队协作和集成数量上全面领先
- ClickUp 在项目管理深度和性价比上有优势
- Microsoft Loop 等巨头产品进入同一赛道

---

## 八、附录：数据来源

| 编号 | 来源 | URL |
|------|------|-----|
| [1] | Notion 官方产品页 | https://www.notion.so/product |
| [2] | Notion 块类型文档 | https://www.notion.so/help/writing-and-editing-basics |
| [3] | Notion 数据库限制 | https://www.notion.so/help/database-limits |
| [4] | Notion 协作功能 | https://www.notion.so/product |
| [5] | Notion 集成市场 | https://www.notion.so/integrations |
| [6] | Notion API 文档 | https://developers.notion.com |
| [7] | Notion 导出设置 | https://www.notion.so/help/export-your-content |
| [8] | Notion AI 功能页 | https://www.notion.so/product/ai |
| [9] | Notion 定价页 | https://www.notion.so/pricing |
| [10] | Notion 客户案例 | https://www.notion.so/customers |

---

*本报告由 AgentDrivenCompetBench 多 Agent 协作系统自动生成。采集时间：2026-06-15。*
`

function demoComplete(): SSEComplete {
  return {
    final_status: 'completed',
    competitor_name: 'Notion',
    industry: 'saas',
    qa_score: 0.82,
    report_markdown: REPORT_MD,
    feedback_history: [
      {
        iteration: 1,
        verdict: 'revise',
        score: 0.58,
        issues_count: 8,
        critical_issues: 2,
        action_taken: '打回 collector 补充 AI 功能、集成生态、移动端数据',
        feedback_summary: '数据覆盖不足：缺少 AI features、integrations、mobile experience 等关键维度',
        issues: [
          {
            field_path: 'ai_features',
            field_label: 'AI 功能',
            severity: 'critical',
            issue_type: 'missing_dimension',
            reason_label: '数据缺失',
            description: '未采集到 AI 功能相关数据',
            suggestion: '增加 notion.so/product/ai 等页面',
          },
          {
            field_path: 'integrations',
            field_label: '集成生态',
            severity: 'critical',
            issue_type: 'missing_dimension',
            reason_label: '数据缺失',
            description: '未采集到集成生态信息',
            suggestion: '增加 notion.so/integrations 页面',
          },
        ],
        resolved_fields: [],
        regressed_fields: [],
        persisted_fields: ['pricing', 'features'],
      },
      {
        iteration: 2,
        verdict: 'pass',
        score: 0.82,
        issues_count: 1,
        critical_issues: 0,
        action_taken: '通过，所有维度达标',
        feedback_summary: '第二次采集补齐了 AI、集成、移动端等维度，报告质量达到发布标准',
        issues: [],
        resolved_fields: ['ai_features', 'integrations', 'mobile_experience', 'user_personas'],
        regressed_fields: [],
        persisted_fields: ['pricing', 'features', 'security_compliance'],
      },
    ],
    agent_traces: [
      {
        agent: 'discovery', iteration: 1, duration_ms: 420, model: 'deepseek-chat',
        input_tokens: 200, output_tokens: 350,
        prompt_preview: 'Discover URLs for Notion...', output_preview: '["https://www.notion.so/product", ...]',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'collector', iteration: 1, duration_ms: 5200, model: 'deepseek-chat',
        input_tokens: 48000, output_tokens: 3200,
        prompt_preview: 'Extract claims from Notion pages...', output_preview: '36 claims extracted',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'analyst', iteration: 1, duration_ms: 2800, model: 'deepseek-chat',
        input_tokens: 12000, output_tokens: 4500,
        prompt_preview: 'Aggregate claims into CompetitorProfile...', output_preview: '{\n  "company_name": "Notion",\n  ...',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'writer', iteration: 1, duration_ms: 1800, model: 'deepseek-chat',
        input_tokens: 6000, output_tokens: 8000,
        prompt_preview: 'Write competitive analysis report...', output_preview: '# Notion 竞品分析报告...',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'qa', iteration: 1, duration_ms: 1500, model: 'deepseek-chat',
        input_tokens: 14000, output_tokens: 1200,
        prompt_preview: 'Review report quality...', output_preview: '{"verdict": "revise", ...}',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'collector', iteration: 2, duration_ms: 3200, model: 'deepseek-chat',
        input_tokens: 24000, output_tokens: 2800,
        prompt_preview: '补采缺失维度...', output_preview: '18 claims extracted',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'analyst', iteration: 2, duration_ms: 2200, model: 'deepseek-chat',
        input_tokens: 10000, output_tokens: 3800,
        prompt_preview: 'Merge new claims into profile...', output_preview: '{\n  "company_name": "Notion",\n  ...',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'writer', iteration: 2, duration_ms: 1600, model: 'deepseek-chat',
        input_tokens: 5000, output_tokens: 9000,
        prompt_preview: 'Regenerate report with complete data...', output_preview: '# Notion 竞品分析报告...',
        timestamp: new Date().toISOString(),
      },
      {
        agent: 'qa', iteration: 2, duration_ms: 1200, model: 'deepseek-chat',
        input_tokens: 15000, output_tokens: 800,
        prompt_preview: 'Final review...', output_preview: '{"verdict": "pass", "score": 0.82}',
        timestamp: new Date().toISOString(),
      },
    ],
    trace_id: 'demo-trace-notion-20260615',
  }
}

/** 预录演示事件序列 — 模拟 Notion 竞品分析完整流程（含一轮 QA 打回） */
export const DEMO_EVENTS: DemoEvent[] = [
  // ── 第 1 轮：Discovery → Collector → Analyst → Writer → QA (revise) ──
  {
    delay: 400,
    event: { type: 'agent_start', data: { agent: 'discovery', iteration: 1 } },
  },
  {
    delay: 300,
    event: { type: 'log', data: { message: 'Discovery: 搜索 "Notion SaaS 竞品" ...', agent: 'discovery' } },
  },
  {
    delay: 500,
    event: { type: 'log', data: { message: 'Discovery: 发现 5 个高价值 URL (优先级排序)', agent: 'discovery' } },
  },
  {
    delay: 300,
    event: { type: 'agent_end', data: { agent: 'discovery', iteration: 1, duration_ms: 420 } },
  },
  // Collector + 4 并行子采集
  {
    delay: 400,
    event: { type: 'agent_start', data: { agent: 'collector', iteration: 1 } },
  },
  {
    delay: 200,
    event: { type: 'sub_agent_start', data: { parent: 'collector', sub_id: 'sub-1', url: 'https://www.notion.so/pricing', iteration: 1 } },
  },
  {
    delay: 150,
    event: { type: 'log', data: { message: '正在抓取: notion.so/pricing ...', agent: 'collector' } },
  },
  {
    delay: 100,
    event: { type: 'sub_agent_start', data: { parent: 'collector', sub_id: 'sub-2', url: 'https://www.notion.so/product', iteration: 1 } },
  },
  {
    delay: 100,
    event: { type: 'sub_agent_start', data: { parent: 'collector', sub_id: 'sub-3', url: 'https://www.notion.so/integrations', iteration: 1 } },
  },
  {
    delay: 100,
    event: { type: 'sub_agent_start', data: { parent: 'collector', sub_id: 'sub-4', url: 'https://www.notion.so/product/ai', iteration: 1 } },
  },
  // Sub 1 完成
  {
    delay: 1200,
    event: { type: 'sub_agent_end', data: { parent: 'collector', sub_id: 'sub-1', url: 'https://www.notion.so/pricing', iteration: 1, success: true, claims_count: 12, duration_ms: 1200 } },
  },
  {
    delay: 300,
    event: { type: 'log', data: { message: 'notion.so/pricing: 提取 12 条 claim', agent: 'collector' } },
  },
  // Sub 2 完成
  {
    delay: 400,
    event: { type: 'sub_agent_end', data: { parent: 'collector', sub_id: 'sub-2', url: 'https://www.notion.so/product', iteration: 1, success: true, claims_count: 10, duration_ms: 1600 } },
  },
  {
    delay: 200,
    event: { type: 'log', data: { message: 'notion.so/product: 提取 10 条 claim', agent: 'collector' } },
  },
  // Sub 3 完成
  {
    delay: 500,
    event: { type: 'sub_agent_end', data: { parent: 'collector', sub_id: 'sub-3', url: 'https://www.notion.so/integrations', iteration: 1, success: true, claims_count: 6, duration_ms: 2100 } },
  },
  {
    delay: 200,
    event: { type: 'log', data: { message: 'notion.so/integrations: 提取 6 条 claim', agent: 'collector' } },
  },
  // Sub 4 完成
  {
    delay: 300,
    event: { type: 'sub_agent_end', data: { parent: 'collector', sub_id: 'sub-4', url: 'https://www.notion.so/product/ai', iteration: 1, success: true, claims_count: 8, duration_ms: 1800 } },
  },
  {
    delay: 200,
    event: { type: 'log', data: { message: 'notion.so/product/ai: 提取 8 条 claim', agent: 'collector' } },
  },
  // Collector 收尾
  {
    delay: 600,
    event: { type: 'log', data: { message: 'Collector 第 1 轮完成: 4/4 URL 成功, 共 36 条 claim', agent: 'collector' } },
  },
  {
    delay: 200,
    event: { type: 'agent_end', data: { agent: 'collector', iteration: 1, duration_ms: 5200 } },
  },
  // Analyst
  {
    delay: 500,
    event: { type: 'agent_start', data: { agent: 'analyst', iteration: 1 } },
  },
  {
    delay: 600,
    event: { type: 'log', data: { message: 'Analyst: 聚合 36 条 claim → 结构化竞品画像...', agent: 'analyst' } },
  },
  {
    delay: 1200,
    event: { type: 'log', data: { message: 'Analyst: SWOT 分析完成，识别 3 个数据缺口', agent: 'analyst' } },
  },
  {
    delay: 800,
    event: {
      type: 'agent_end',
      data: {
        agent: 'analyst', iteration: 1, duration_ms: 2800,
        report_preview: '# Notion 竞品分析 (草稿)\n\n> ⚠️ 数据不完整 — 缺少集成生态、AI功能详情',
      },
    },
  },
  // Writer
  {
    delay: 400,
    event: { type: 'agent_start', data: { agent: 'writer', iteration: 1 } },
  },
  {
    delay: 1000,
    event: { type: 'log', data: { message: 'Writer: 生成第 1 版报告 (Markdown, 含脚注溯源)...', agent: 'writer' } },
  },
  {
    delay: 800,
    event: {
      type: 'agent_end',
      data: {
        agent: 'writer', iteration: 1, duration_ms: 1800,
        report_preview: '# Notion 竞品分析 (草稿 v1)\n\n> ⚠️ 数据不完整 — 维度缺失: AI功能、集成生态',
      },
    },
  },
  // QA → Revise
  {
    delay: 500,
    event: { type: 'agent_start', data: { agent: 'qa', iteration: 1 } },
  },
  {
    delay: 800,
    event: { type: 'log', data: { message: 'QA: 规则校验 + LLM 语义审查中... 发现 8 个问题', agent: 'qa' } },
  },
  {
    delay: 1200,
    event: {
      type: 'qa_verdict',
      data: {
        verdict: 'revise', score: 0.58, iteration: 1,
        missing_dimensions: ['ai_features', 'integrations', 'mobile_experience', 'user_personas'],
        issues_count: 8,
        target_agent: 'collector',
      } as SSEQaVerdict,
    },
  },
  {
    delay: 600,
    event: {
      type: 'log',
      data: {
        message: 'QA verdict: REVISE (score: 0.58), 缺失维度: ai_features, integrations, mobile_experience — 打回 collector',
        agent: 'qa',
      },
    },
  },
  {
    delay: 400,
    event: { type: 'agent_end', data: { agent: 'qa', iteration: 1, duration_ms: 1500 } },
  },
  {
    delay: 500,
    event: {
      type: 'iteration_summary',
      data: {
        iteration: 1,
        verdict: 'revise',
        score: 0.58,
        issues_count: 8,
        critical_issues: 2,
        action_taken: '打回 collector 补充数据',
        feedback_summary: '数据覆盖不足：缺少 AI features、integration、mobile experience 等关键维度，报告完整度 58%',
        issues: [],
        resolved_fields: [],
        regressed_fields: [],
        persisted_fields: ['pricing', 'features'],
      },
    },
  },

  // ── 第 2 轮：补采 → 重新分析 → 通过 ──
  {
    delay: 2000,
    event: { type: 'agent_start', data: { agent: 'collector', iteration: 2 } },
  },
  {
    delay: 400,
    event: { type: 'log', data: { message: 'Collector 第 2 轮: 补采缺失维度 (AI、集成、移动端)...', agent: 'collector' } },
  },
  {
    delay: 1000,
    event: { type: 'log', data: { message: '补采完成: 新增 18 条 claim, 全部 4 个维度覆盖', agent: 'collector' } },
  },
  {
    delay: 400,
    event: { type: 'agent_end', data: { agent: 'collector', iteration: 2, duration_ms: 3200 } },
  },
  {
    delay: 400,
    event: { type: 'agent_start', data: { agent: 'analyst', iteration: 2 } },
  },
  {
    delay: 1500,
    event: { type: 'log', data: { message: 'Analyst: 合并新旧数据，重新生成竞品画像...', agent: 'analyst' } },
  },
  {
    delay: 600,
    event: { type: 'agent_end', data: { agent: 'analyst', iteration: 2, duration_ms: 2200 } },
  },
  {
    delay: 300,
    event: { type: 'agent_start', data: { agent: 'writer', iteration: 2 } },
  },
  {
    delay: 1200,
    event: { type: 'log', data: { message: 'Writer: 生成最终版报告 (含 10 个脚注溯源)...', agent: 'writer' } },
  },
  {
    delay: 500,
    event: {
      type: 'agent_end',
      data: { agent: 'writer', iteration: 2, duration_ms: 1600 },
    },
  },
  {
    delay: 400,
    event: { type: 'agent_start', data: { agent: 'qa', iteration: 2 } },
  },
  {
    delay: 800,
    event: { type: 'log', data: { message: 'QA: 最终审查 — 所有维度达标 (score: 82%)', agent: 'qa' } },
  },
  {
    delay: 800,
    event: {
      type: 'qa_verdict',
      data: {
        verdict: 'pass', score: 0.82, iteration: 2,
        missing_dimensions: [] as string[],
      } as SSEQaVerdict,
    },
  },
  {
    delay: 400,
    event: { type: 'agent_end', data: { agent: 'qa', iteration: 2, duration_ms: 1200 } },
  },
  {
    delay: 500,
    event: {
      type: 'iteration_summary',
      data: {
        iteration: 2,
        verdict: 'pass',
        score: 0.82,
        issues_count: 1,
        critical_issues: 0,
        action_taken: '通过，质量达标',
        feedback_summary: '第二轮补齐了 AI、集成、移动端等维度数据，整体质量提升至 82%，达到发布标准',
        issues: [],
        resolved_fields: ['ai_features', 'integrations'],
        regressed_fields: [],
        persisted_fields: ['pricing', 'features', 'security_compliance'],
      },
    },
  },

  // ── 完成 ──
  {
    delay: 800,
    event: {
      type: 'complete',
      data: demoComplete(),
    },
  },
]

/** Demo 总时长估计（毫秒）用于进度条 */
export const DEMO_TOTAL_DURATION = DEMO_EVENTS.reduce((sum, e) => sum + e.delay, 0)
