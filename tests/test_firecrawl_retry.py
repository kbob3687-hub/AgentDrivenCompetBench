"""测试 Firecrawl fetch 重试逻辑 + PII 正则精度"""

from __future__ import annotations

import pytest

from agents.collector.compliance import redact_pii


class TestPIIRegexPrecision:
    """确保 PII 正则不会误匹配价格、ID、版本号等常见数字"""

    def test_price_not_matched_as_phone(self):
        texts = ["¥138/人/月", "价格从199到1299不等", "13800元/年", "15999"]
        for t in texts:
            _, counts = redact_pii(t)
            assert "[手机号]" not in counts, f"误匹配: {t}"

    def test_long_number_not_matched_as_bank_card(self):
        texts = ["订单号: 20240531120000", "ID: 1234567890123", "v1.3.9.20240101"]
        for t in texts:
            _, counts = redact_pii(t)
            assert "[银行卡]" not in counts, f"误匹配: {t}"

    def test_example_email_not_matched(self):
        _, counts = redact_pii("user@example.com")
        assert "[邮箱]" not in counts

    def test_real_phone_matched(self):
        out, counts = redact_pii("联系 13812345678 咨询")
        assert counts.get("[手机号]") == 1
        assert "13812345678" not in out

    def test_real_email_matched(self):
        out, counts = redact_pii("发送到 zhangsan@gmail.com")
        assert counts.get("[邮箱]") == 1
        assert "zhangsan@gmail.com" not in out


class TestFirecrawlRetrySignature:
    """验证 firecrawl_fetch 函数签名支持 max_retries 参数"""

    def test_function_accepts_max_retries(self):
        import inspect
        from agents.collector.tools import firecrawl_fetch

        sig = inspect.signature(firecrawl_fetch)
        assert "max_retries" in sig.parameters
        assert sig.parameters["max_retries"].default == 2
