# Agent Benchmark V1.1

本目录只评测 `workflow_id = standalone`，真实入口为
`orchestrator.graph.run_pipeline()`。结果不代表 API/SSE 工作流，也不包含跨竞品比较报告。
一个 case 中的每个 competitor 都执行一个独立真实任务；重复运行也会重新调用模型。

## 安装与运行

在仓库根目录执行（Python 3.11+）：

```powershell
python -m pip install -e ".[dev]"
python -m benchmark.runner --case notion-core-001 --max-iterations 1 --timeout 900
python -m benchmark.runner --repeat 3
python -m benchmark.runner --case notion-core-001 --capture-sources
```

Runner 加载仓库 `.env`，但不覆盖进程已有环境变量。当前四个 LLM Agent 默认使用
`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`，并沿用项目 Langfuse、
Firecrawl、HTTP、Playwright 配置。可以用 `--model` 覆盖本进程的模型名。
Standalone 不需要启动 Web 服务或数据库，不需要人工 HITL 确认。

任务默认串行、QA 开启、最多 3 次 QA、超时 900 秒。超时会取消当前任务，然后继续后续任务。
`--max-iterations 1` 只做一次 QA，不能用于观察 QA 返工收益。

```powershell
python -m benchmark.runner --case notion-vs-clickup-001 --repeat 3 --max-iterations 3 --enable-qa
python -m benchmark.runner --case notion-vs-clickup-001 --repeat 3 --max-iterations 3 --no-enable-qa
```

两组运行均生成独立目录；保持模型、输入、代码、采集配置和超时一致，比较相同 competitor
和 repeat 的质量与成本。网页和模型会波动，3 次重复只是初步观察，不构成统计显著性结论。
较严格的实验应交错执行两组，避免运行时间成为混淆因素。

## 输入

`cases/cases.json` 包含 3 个真实任务定义，没有预制结果或期望分数。
`--cases <path>` 可指定自定义 JSON 数组；`--case <id>` 可重复传入以筛选。

```json
{
  "id": "notion-vs-clickup-001",
  "competitors": ["Notion", "ClickUp"],
  "required_dimensions": ["features", "pricing", "persona", "swot"]
}
```

可选字段：`collect_scope`、按 competitor 映射的 `target_urls`、`template`。
`template` 只用于评测现有行业扩展定义，不会改变 standalone 的行业模板注入行为。
扩展维度用 `extensions.<field_name>`，并指定现有 template（如 `saas`）。
未指定 collect_scope 时，核心报告维度映射为采集维度；要求 SWOT 时采集
pricing/features/user_personas。SWOT 不会加入 Collector 原始维度或 QA 的采集维度要求。

## 指标精确定义

每个指标保存 `value`、可用时的 `numerator` / `denominator`、`reason`、`details`。
Evaluator 不联网、不调用模型、不修复输出后再评分。

| 指标 | 定义 |
|---|---|
| workflow_success | workflow 正常返回，有非空字典 profile 和非空白 report_markdown，且没有节点错误输出、未捕获异常或超时。QA reject / 达到轮数上限本身不是失败。内部重试恢复后正常返回不算节点错误。Schema 是否合格另算。 |
| qa_passed | QA 开启且观察到判定时，最终 verdict 是否为 pass；未执行/关闭为 null。异常前已观察到的 QA 仍可展示，不能代替 workflow_success。 |
| schema_valid | 对最终原始 profile 执行现有 CompetitorProfile.model_validate；缺失结果为 false；保留校验错误位置。Pydantic 的默认值和类型转换沿用现有 Schema。 |
| citation_coverage | 应带证据的 Claim 槽位中，至少存在一个 source 对象的比例。空 source 对象也表示引用存在，但 validity 不通过。缺失/错误格式的 Claim 不过滤掉。 |
| citation_validity | 已有 source 条目中，通过 SourceReference 校验、有合法 HTTP(S) URL、非空字符串 title/snippet 的比例。标量错误引用也进分母；按引用出现次数统计，不按唯一 URL 去重。 |
| dimension_coverage | 满足要求的维度数 / 去重并归一化后的要求维度数。features→feature_tree，persona→user_personas。features 至少一个有名称功能；persona 至少一个有 segment 的画像；pricing 有非空 model_type；SWOT 四类都各有非空 claim 才算该维度覆盖，四类另列布尔值；扩展字段按现有模板识别并检查非空，0/false 有意义。结构合法性和引用合法性独立衡量。 |
| qa_first_pass | 第一次 QA feedback verdict 是否 pass；没有反馈或 QA 关闭为 null。 |
| qa_iterations | 实际开始执行 QA 节点的次数，包括执行失败的 QA；没有执行为 0。 |
| retry_count | QA revise/reject 后，实际开始执行下一次 Collector/Analyst/Writer 返工的次数。终止 reject 不算返工，最后一次 revise 未启动返工也不算；不等于 API 重试数。 |
| latency | Runner 用 perf_counter 测得的单任务工作流墙钟秒数；包含 Discovery、抓取、LLM、QA、返工及内部重试，不含评测和写文件。失败/超时同样记录。 |
| token_usage | 所有记录到的 LLM 调用 API 返回的 input+output token 总和，包含 QA 和已观测重试调用。任何调用 usage 缺失或执行审计不完整则为 null；details 仍列已观测 token，不能当完整总成本。未发生 LLM 调用且正常完整结束时可为真实 0。 |
| llm_judge_score | 始终 null，reason=disabled_in_v1。业务 QA 不是独立 Judge。 |
| feature/pricing/persona/swot_evidence_count | 各维度中，非空 Claim 且至少有一个结构合法引用的 EvidencedClaim 槽位数。feature_tree 递归包含子功能；persona 包含 pain_points 和 satisfaction_signals；SWOT 合并四类；pricing 使用 evidence。重复 Claim 文本出现在不同槽位时分别计数。 |
| feature/pricing/persona/swot_unique_source_count | 同一维度中支撑上述有效证据 Claim 的不同合法 HTTP(S) URL 数。 |
| evidence_count / unique_source_count | 全部四个核心维度及证据型 extensions 的上述总数；唯一 URL 跨维度去重。 |
| pricing_tier_count / pricing_has_tiers | `pricing.tiers` 中通过现有 PricingTier Schema 校验的档位数，以及是否大于零。明确空列表为 0/false；字段缺失或结构错误为 null。 |

深度指标仅统计现有 Schema 指定的 Claim 槽位，不判断事实真实性或内容是否有信息量。
其“有效证据”需要非空 Claim 和至少一个符合 citation_validity 同口径结构要求的引用；
因此 `evidence_count` 与 `citation_coverage` 的定义不同。URL 去重规则：使用 Pydantic
`HttpUrl` 规范化 scheme、host、默认端口；移除 fragment；空 path 视为 `/`；保留 path
大小写、query 文本及参数顺序。不会访问 URL。合法引用缺失或非法时不贡献深度计数。

维度字段明确为空列表时，证据数与 URL 数为 0；整个 profile 缺失、维度字段缺失或类型
错误时，相应指标为 null 并记录 reason。若核心维度不完整，总体计数为 null，并在 details
列出缺失或错误字段。`pricing=null` 表示该可选维度明确无证据（计数 0），但档位数量未知
（null）；`pricing.tiers=[]` 才表示已知没有档位。聚合时 null 始终不作为 0。

零 Claim → citation_coverage=null/no_claims；零引用 → citation_validity=null/no_sources。
profile 整个缺失时 dimension_coverage=0、schema_valid=false、workflow_success=false。
缺失可选父维度不凭空制造 Claim；有 pricing/feature 等对象却缺 evidence/description 时，
该证据槽位进入引用覆盖分母。嵌套功能、persona 痛点/满意度、SWOT、定价和证据型扩展均覆盖。

汇总采用任务等权平均，布尔均值即比例；null 不进入条件均值，但明确展示 available/missing。
workflow_success/schema_valid 的失败任务不会从分母中删掉。每个 case 提供同口径汇总，
以及所有 competitor × repeat 是否全部成功。没有加权综合总分，没有伪造人工基线。
为避免失败样本从质量比较中消失，metrics 另提供 `all_tasks_summary`：以计划任务数为分母，
未执行、失败或 null 的质量任务记 0；`task_counts` 展示 planned/completed/error/timeout。
条件均值用于观察成功产出的质量，全任务均值用于系统间比较，两者必须一起阅读。

QA 要求 Collector 返工时，standalone 会先重新进入 Discovery。用户指定的 URL 视为
来源边界；没有未采过的新 URL，或新 URL 没带来新 claim/source，流程以
`final_status=source_limited` 正常结束，并保留原报告及真实 QA verdict。
此时 `workflow_success` 仍按是否有有效产出判断，`qa_passed=false`；报告是未通过 QA 的草稿。
异常则以 `final_status=failed` 结束，保留最早发生的节点错误。

## 产物与复现

```text
benchmark/results/<UTC时间-随机ID>/
  manifest.json
  raw/<task_id>.json
  raw/<task_id>.md          # 当任务产出报告时
  metrics.json
  report.md
```

原始 JSON 保存 workflow 状态、真实中间节点输出、LLM usage、错误、时间。
任务报告还列出 final_status、返工停止原因和未补齐维度，方便区分“正常结束但质量不足”与异常。
manifest 保存 workflow_id、case 快照、模型配置、enable_qa、运行时间、Git commit/dirty、
源码/Prompt/模板哈希、Python 与关键依赖版本。密钥不写入 manifest。
结果目录默认 gitignore；异常和超时也落盘，不用 mock 补齐真实报告。
每个任务完成后刷新报告，进程被强制结束时已完成任务结果仍保留；未执行任务不算已运行样本。

重新评价已有真实原始结果，不调用 Agent，保留原报告：

```powershell
python -m benchmark.runner --rescore "benchmark/results/<run_id>"
```

输出 `metrics.rescored.json` / `report.rescored.md`。使用当前 evaluator/Schema/模板；
如这些规则变化，应把它作为新的评测版本对待，不覆盖原始实验。

配对比较两个已保存 run（例如 QA 开/关）：

```powershell
python -m benchmark.compare benchmark/results/<run_a> benchmark/results/<run_b> --out benchmark/results/<run_a>_vs_<run_b>
```

默认要求两个 run 都保存了 `source_snapshots/<task>/index.json`；缺少运行当时网页原文的
运行无法人工复核，不能用于正式质量对比，`--allow-missing-sources` 仅用于探索性比较。
比较前会校验 cases、模型配置、Git commit、repeat、timeout 等配置一致。输出按
case/competitor/repeat 配对，给出 A/B 均值、B-A 配对差值、缺失配对，以及失败/缺失记 0
的全任务质量口径。

## 测试与限制

```powershell
python -m pytest tests/benchmark -q
python -m pytest tests/test_orchestrator.py tests/test_schemas.py tests/test_qa_validators.py tests/test_fan_out_subagent.py -q
```

Evaluator 测试用人工 fixtures；Runner/图测试可 mock 来验证框架行为，产物只写 pytest 临时目录，
这些数据不作为正式 Benchmark 结果。正式 CLI 没有 mock 模式，始终调用真实 standalone workflow。

人工内容质量标尺见 [`gold/README.md`](gold/README.md)。旧运行缺少当时的完整来源正文；
回溯快照与真实采集时快照必须区分。人工标签未签核前不输出人工质量分数。

V1 不验证网页当前可达性、snippet 真伪、事实准确性和 Markdown 每条事实的引用。
Schema 已强制 claims 带 sources，因此 citation_coverage 在有效 profile 上可能接近 100%；
必须结合维度覆盖与 validity 阅读，不能据此声称事实全部正确。
token 仅为 API 已报告 usage，不推测网络失败请求、SDK 隐藏重试的账单或缓存 token 费用，
不统计抓取服务美元费用。模型/Prompt/Workflow 比较通过相同 cases 的独立运行完成，
Prompt/Workflow 版本由 Git 与源码哈希区分；尚未实现可视化实验平台、统计显著性或独立 Judge。
