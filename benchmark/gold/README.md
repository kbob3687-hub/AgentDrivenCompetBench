# 小型人工质量标尺（待人工签核）

## 2026-09-24 采集时快照样本

`phase1_cases.json` 启动了 Notion、ClickUp、OpenProject 三个真实 standalone case，
均开启 QA 与 `--capture-sources`。首轮 OpenProject 在 Collector 阶段因 LLM 响应解析错误
结束，保留在原始 run 中，不能当作内容质量样本；`openproject_recovery_case.json` 将来源
约束为官方 features 页后重跑成功，最终 QA 未通过并以 `source_limited` 结束。最终三份
**有 profile 和报告**的样本由 `phase1_selection.json` 固定：

- Notion：`20260924T025206Z-9838847b`，2/2 次来源抓取成功，QA pass。
- ClickUp：同一 run，3/3 次抓取成功（定价页因内部重试抓取两次），QA pass。
- OpenProject：`20260924T030259Z-53a6a170`，3/3 次抓取成功（同一页因内部重试
  抓取三次），QA revise 后 `source_limited`。失败的首轮在
  `20260924T025206Z-9838847b` 保留，未纳入人工内容评审。

每次 Collector 抓取实际交给 LLM 前的脱敏正文在对应 run 的
`source_snapshots/<task_id>/`，`index.json` 留存 URL、抓取时间、方法、成功/失败与
全文 SHA-256；同 URL 的重试也逐次保留。`assemble_review.py` 校验 raw、报告与全部
来源正文的文件和哈希后，生成 [phase1_review.draft.json](phase1_review.draft.json)：
**3 个 case、15 个检查点，verdict 全为 null**。检查点按固定规则取每份报告的定价、
第一条功能/画像/SWOT 结论，以及缺失说明。人工评审需逐项检查原始报告、所引 snippet
和对应采集时正文，再填写判断与依据；目前没有人工质量分数。运行目录被 Git 忽略，
需要长期保存时应连同 `manifest.json`、`raw/` 和 `source_snapshots/` 一起归档。

```powershell
python -m benchmark.gold.prepare_live benchmark/results/20260924T025206Z-9838847b
python -m benchmark.gold.prepare_live benchmark/results/20260924T030259Z-53a6a170 --expected-tasks 1
python -m benchmark.gold.assemble_review benchmark/gold/phase1_selection.json
```

以上生成器默认拒绝覆盖已有评审草稿；命令用于新的 run 或在归档副本中重建。

### 2026-10-28 人工签核完成

15 个检查点已由人工逐项核对运行当时快照后定稿：10 条 `supported`、2 条 `partial`
（Notion 定价账期表述、OpenProject「免费」为无来源推断）、3 条 `honest`。
定稿文件 [phase1_review.completed.json](phase1_review.completed.json)，署名「硝酸铜」，
评审时间 `2026-10-28T21:31:56+08:00`。复核时以相同 `direct_http` 通道重爬
`openproject.org/features`，正文长度 22108 字节、SHA-256 `9c5dcd3a5f9e…` 与存档
完全一致，30 个引用关键词零漂移；该一致只证明这一静态页面本次稳定，不替代
存档优先的复核原则。

签核校验由 [phase1_signoff.py](phase1_signoff.py) 执行：

```powershell
python -m benchmark.gold.phase1_signoff --review benchmark/gold/phase1_review.completed.json
```

校验器以 `phase1_review.draft.json` 为不可变出处基线，要求 status 为
`human_reviewed`、实名署名、带时区的评审时间；逐项核对 15 个检查点的 verdict、
依据、理由，并重新计算 raw 与全部 in-workflow 来源快照的 SHA-256 防篡改；全部通过
才生成 `phase1_review.summary.json`（只列判断次数，不做综合分）。

### 判据缺口（下一轮选点时补）

2026-10-28 评审发现：OpenProject 报告中建筑行业画像引用的原文标注 BIM 能力为
**Add-ons**（需额外付费），报告使用场景未保留该前提；现有 15 项判据
（`missing_disclosure` 只管「没抓到的要标未知」）未覆盖此类「来源中的前提
（付费、需插件、仅企业版、地域限制）在转述时丢失」的问题。下一轮选检查点时
应将其纳入 `missing_disclosure` 判据范围，无需新增判据名。

## 历史回溯资料

此前挑选了 **3 个真实 case ID、4 个真实 standalone workflow 子任务**：Notion、
ClickUp、OpenProject 的 QA-pass 产出，以及受单一来源限制的 Notion 产出。选择理由分别是
常规报告与“知道信息不足但可能过度断言”的反例。原始运行记录仍在 `benchmark/results/`；
`corpus.json` 固定了其路径，快照索引固定原始记录 SHA-256。

## 来源快照的时间边界

旧 raw **没有保存 Collector 当时抓到的网页正文**。本目录的 `snapshots/` 是在评审时
重新抓取的 12 个被引 URL：10 个成功，两个 G2 页面返回 HTTP 403。索引保存 URL、
抓取时间、成功/失败、正文 SHA-256 和文件名。它只能用于回溯核对，**不能证明旧运行
当时的网页内容**；内容可能变动，尤其价格和币种。正文及索引默认被 Git 忽略，
避免意外提交第三方网页全文。不要为失败页面补造快照。
索引另列出旧 raw 中 Collector 留下的短 `snapshot_hash`；本次重新抓取的正文哈希与
这些旧哈希均不一致。抓取方法、脱敏或网页变化都可能造成差异，不能据此倒推出旧页面内容。

未来真实运行可加 `--capture-sources`，在 Collector 抓取后、LLM 提取前保存它实际看到的
脱敏正文，存于该 run 的 `source_snapshots/<task_id>/`，含每次成功或失败记录、抓取方法、
时间、SHA-256。该选项不增加网络请求或 LLM 调用；它是本项目可用的“运行当时”快照。

```powershell
python -m benchmark.runner --case notion-core-001 --capture-sources
```

## 人工评审规则

`review_queue.json` 预先固定 13 个检查点，防止看完结果后挑有利样本。每个任务至少检查
定价依据、关键结论的片段支持、信息缺失的表述。评审者同时看 raw、报告、引用 snippet
和来源快照，并在 `review.draft.json` 中逐项填写 verdict、具体依据位置和判断理由。

- `pricing_basis`、`snippet_support`：`supported` / `partial` / `unsupported` /
  `unverifiable`。一个结论由多个子事实拼成时，只有全部关键子事实获得相应引用片段
  支持才算 supported；部分支持记 partial。网页抓不到、或后抓网页与旧运行存在
  无法排除的时效差异，记 unverifiable。
- `missing_disclosure`：`honest` / `misleading` / `not_applicable` / `unverifiable`。
  “本轮未采到”是范围说明；把“本轮未查到公开价格”写成“产品没有公开价格”属于
  可能误导。若没有相关缺口才用 not_applicable。
- 引用 URL 格式、证据条数、唯一 URL 数和定价层级数只作诊断，不自动加质量分。
  不从这些数量推断片段支持或事实正确。

```powershell
python -m benchmark.gold.review --prepare
# 人类评审者填写 benchmark/gold/review.draft.json，另存 review.completed.json
python -m benchmark.gold.review --review benchmark/gold/review.completed.json
```

只有全部 13 项有真实评审者署名、带时区的评审时间、verdict、依据位置和理由，且 raw 与
来源快照哈希未变时，才生成 `review.summary.json`。汇总只列各类判断次数，不做综合分。
当前 draft 的所有 verdict 均为 null，**尚未形成可信人工质量分数**。

一次新运行已验证 `--capture-sources`：`clickup-pricing-source-001` 实际抓取 ClickUp
定价页并保存 13,145 字节脱敏正文，保存文件的 SHA-256 与快照索引一致；该任务
`workflow_success=true`、`qa_passed=false`。这份新运行不自动加入人工金标；
若要纳入，应先按相同规则固定检查点并由人评审。

预审时发现两个值得人工核查的例子：OpenProject 报告把“3.8/5（25 条）”归给 G2，
回溯抓到的厂商 reviews 页将该数字列在 GetApp 下；单来源 Notion 报告写“未公开价格层级”，
而回溯抓到的官方 pricing 页列有 Free、Plus、Business、Enterprise。两者都需结合
“网页抓取晚于原运行”的限制，由评审者最终判定。
