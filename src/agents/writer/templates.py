"""WriterAgent报告模板 - Markdown格式"""

FULL_REPORT_TEMPLATE = """# {product_name} 竞品分析报告

> 生成时间：{generated_at}
> 数据完整度：{completeness_score:.0%}
> 分析维度：{dimensions}

---

## 一、产品概览

| 项目 | 信息 |
|------|------|
| 公司名称 | {company_name} |
| 产品名称 | {product_name} |
| 官网 | {website} |
| 行业 | {industry} |
| 产品定位 | {one_liner} |

---

## 二、定价分析

{pricing_section}

---

## 三、核心功能

{feature_section}

---

## 四、SWOT分析

{swot_section}

---

## 五、关键洞察

{insights_section}

---

## 附录：数据来源

{sources_section}

---

*本报告由竞品分析多Agent系统自动生成，所有结论均附带数据来源，可点击角标查看原始证据。*
"""

PRICING_TABLE_TEMPLATE = """### 定价模式：{model_type}

| 层级 | 价格 | 计费周期 | 主要功能 | 限制 |
|------|------|----------|----------|------|
{tier_rows}

{pricing_notes}
"""

FEATURE_SECTION_TEMPLATE = """### {category_name}

{feature_items}
"""

SWOT_TABLE_TEMPLATE = """| 类别 | 内容 | 置信度 |
|------|------|--------|
{swot_rows}
"""

EXECUTIVE_SUMMARY_TEMPLATE = """# {product_name} 竞品速览

**产品定位**：{one_liner}

**定价概要**：{pricing_summary}

**核心优势**：
{strengths_summary}

**主要风险**：
{threats_summary}

**建议关注**：
{recommendations}
"""
