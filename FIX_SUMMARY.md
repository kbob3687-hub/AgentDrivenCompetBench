# 修复总结：Collector 采集失败问题

## 问题描述

输入"元气森林"选消费品后，所有数据源采集都失败，3轮迭代后QA一直reject。

## 根本原因分析

### 1. Jina API 配额耗尽（主因）
```
HTTP 402: InsufficientBalanceError: Account balance not enough to run this query
```
Jina Reader API 配额已用完，所有请求返回 402 错误。

### 2. Playwright 中文路径问题（次因）
```
Executable doesn't exist at C:\Users\小米\AppData\Local\ms-playwright\...
```
Windows 用户名包含中文字符"小米"，Playwright 无法正确处理该路径。

### 3. 错误信息不清晰（诊断困难）
原代码中 Jina Reader 失败后直接降级到 Playwright，没有记录 Jina 的失败原因，
导致日志只显示 Playwright 的错误，难以定位真正原因。

## 修复方案

### 1. 新增直接HTTP抓取降级方案（核心修复）

在 `src/agents/collector/tools.py` 中新增 `direct_http_fetch()` 函数：
- 使用 httpx 直接获取 HTML，不依赖外部 API
- 简单的 HTML → 文本转换（去除 script/style/标签）
- 作为 Jina Reader 和 Playwright 之间的降级方案

**降级链变为：**
```
Jina Reader → 直接HTTP抓取 → Playwright（JS渲染页面）
```

### 2. 改进错误日志

在 `src/agents/collector/agent.py` 的 `_fetch_url()` 方法中：
- 每一级降级都记录失败原因
- 最终错误信息汇总所有方法的失败原因

### 3. 添加 Playwright 路径修复脚本

新增 `scripts/setup_playwright.py`：
- 检测用户路径是否包含非 ASCII 字符
- 将 Playwright 浏览器安装到纯英文路径

### 4. FetchResult 新增 fetch_method 字段

记录实际使用的抓取方法，便于诊断和统计。

## 测试结果

| 方法 | baidu.com | sina.com.cn | 163.com |
|------|-----------|-------------|---------|
| Jina Reader | ✅ 8KB | ❌ 超时 | ✅ 47KB |
| 直接HTTP | ✅ 248KB | ✅ 26KB | ✅ 10KB |
| Playwright | ❌ 未安装 | ❌ 未安装 | ❌ 未安装 |

**关键发现：直接HTTP抓取成功处理了 Jina Reader 失败的 URL！**

## 修改的文件

1. `src/agents/collector/tools.py`
   - 新增 `direct_http_fetch()` 函数
   - 新增 `_html_to_text()` 和 `_extract_title_from_html()` 辅助函数
   - 改进 `jina_reader()` 的错误日志
   - 改进 `playwright_fetch()` 的中文路径处理
   - `FetchResult` 新增 `fetch_method` 字段

2. `src/agents/collector/agent.py`
   - 更新 `_fetch_url()` 实现三级降级链
   - 每一级记录失败原因，便于诊断

3. `.env`
   - 添加 Playwright 路径配置说明

4. 新增文件
   - `scripts/setup_playwright.py` - Playwright 安装脚本
   - `scripts/test_fetch_fallback.py` - 降级链测试脚本

## 后续改进建议

1. **Jina API 充值或更换**：如果需要高质量的网页内容提取，考虑充值 Jina API 或使用其他服务
2. **Playwright 安装**：运行 `python scripts/setup_playwright.py` 安装浏览器到纯英文路径
3. **URL 质量优化**：改进 Discovery Agent 的搜索策略，返回更多可抓取的 URL
