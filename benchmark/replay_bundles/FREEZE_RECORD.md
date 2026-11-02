# 正式快照冻结记录（2026-11-02）

正式 case 集：`benchmark/cases/final_cases.json`（6 产品 × 常规/压力 = 12 case，用户已确认冻结）。
冻结包：`benchmark/replay_bundles/<case-id>-c1/`，共 12 个、37 页，全部通过
`SnapshotBundle.load` 哈希校验。

## 采集方式

- 采集脚本：`benchmark/gold/capture_cases.py`，与正式 Collector 完全同链路
  （robots 检查 → Firecrawl → 直连 HTTP → Playwright，含 PII 脱敏），无 LLM 调用。
- 主采集 run：`benchmark/results/capture-20261102T140832Z-fa359a9b/`（第二轮，
  36 个 URL；第一轮 `capture-20261102-superseded/` 已归档）。
- G2 三页因 Firecrawl 限流首轮失败，冷却 45 秒后串行补抓成功（firecrawl），
  成功结果已回填进对应 case 的 `source_snapshots/*/index.json` 后重冻结。

## 与草稿的差异（冻结前修正，均有证据）

| 变更 | 原因 |
|---|---|
| 移除 `capterra.com/p/1/clickup/` | 抓到的是防爬验证壳（264 字符） |
| 移除 `capterra.com/p/1/notion/` | 抓到的是 404 页（1789 字符） |
| 移除 `trello.com/customer-stories` | 浏览器拦截壳（308 字符） |
| `openproject.org/docs/installation-and-operation/` → `/docs/` | 原地址 404；替代页 4929 字符真内容 |

## 冻结纪律（自此刻起生效）

- case 列表、快照包内容、包内 URL 一律不再修改；主实验哪组数字难看也不得换 case。
- 回放时任何包外 URL、任何哈希不符都会硬报错，不存在静默联网兜底。
- 每包来源与抓取时间见各包 `index.json` 的 `observed_at` / `fetch_method`。
