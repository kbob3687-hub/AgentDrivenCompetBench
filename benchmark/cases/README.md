# Case sets

`cases.json`：常规 Notion / ClickUp 任务，作为原有基线，保持不变。

`stress_cases.json`：单独报告的诊断任务，用于检查证据不足和自动发现路径。

| Case | 输入约束 | 要观察的行为 |
|---|---|---|
| notion-single-source-001 | 仅提供 Notion 客户案例页，但仍要求定价、功能、画像与 SWOT | 是否识别缺失维度；返工是否有效；是否在预算内终止 |
| openproject-cold-001 | OpenProject 不在当前 KNOWN_COMPETITORS 预设表，不指定 URL | Discovery cold path 能否找到来源，后续采集、分析和 QA 能否完成 |

这些是测试输入，不包含预制 claims、预期分数或强制 verdict。两组均调用真实 standalone
workflow，使用相同模型与输入，只改变 enable_qa。SWOT 不作为 Collector 原始维度。

单来源 case 是有意收窄来源的边界场景，不能代表开放采集的常规成功率。standalone
把用户指定的 target_urls 当作来源边界。若 QA 要补证据却没有未采过的新 URL，就保留
报告与 QA verdict，以 source_limited 结束；不重复读取同一个页面，也不为通过测试更改输入。

诊断运行先各做一次：

```powershell
python -m benchmark.runner --cases benchmark/cases/stress_cases.json --repeat 1 --max-iterations 3 --timeout 600 --enable-qa
python -m benchmark.runner --cases benchmark/cases/stress_cases.json --repeat 1 --max-iterations 3 --timeout 600 --no-enable-qa
```

这轮用于发现行为和失败模式，不用于统计显著性结论。需要验证稳定性时，保留相同输入重新运行
`--repeat 3`，所有失败样本一起报告，不挑选成功样本。
