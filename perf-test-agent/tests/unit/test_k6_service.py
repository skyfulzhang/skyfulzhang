"""
tests/unit/test_k6_service.py
K6ScriptService 单元测试。
"""

import pytest

from agent.models.test_config import K6TestConfig
from agent.services.k6_service import K6ScriptService, ValidationResult


@pytest.fixture
def service() -> K6ScriptService:
    return K6ScriptService()


@pytest.fixture
def basic_config() -> K6TestConfig:
    return K6TestConfig(
        target_url="https://httpbin.org",  # type: ignore[arg-type]
        test_type="load",
        vus=10,
        duration="30s",
        ramp_up_time="10s",
        ramp_down_time="10s",
        script_name="unit-test",
        description="单元测试配置",
    )


class TestGenerateScriptFromTemplate:
    """generate_script_from_template 方法测试。"""

    def test_generate_load_script_returns_string(
        self, service: K6ScriptService, basic_config: K6TestConfig
    ):
        """生成 load 类型脚本应返回非空字符串。"""
        script = service.generate_script_from_template("load", basic_config)
        assert isinstance(script, str)
        assert len(script) > 100

    def test_generate_fallback_script_contains_export_default(
        self, service: K6ScriptService, basic_config: K6TestConfig
    ):
        """生成的脚本必须包含 export default function。"""
        script = service.generate_script_from_template("load", basic_config)
        # 无论是模板还是 fallback，都应包含此关键字
        assert "export default function" in script

    def test_generate_all_test_types(
        self, service: K6ScriptService, basic_config: K6TestConfig
    ):
        """所有支持的测试类型都应能成功生成脚本。"""
        for test_type in K6ScriptService.TEST_TYPES:
            config = basic_config.model_copy(update={"test_type": test_type})
            script = service.generate_script_from_template(test_type, config)
            assert len(script) > 0, f"测试类型 {test_type} 未能生成脚本"

    def test_generate_script_invalid_type_raises_value_error(
        self, service: K6ScriptService, basic_config: K6TestConfig
    ):
        """不支持的测试类型应抛出 ValueError。"""
        with pytest.raises(ValueError, match="不支持的测试类型"):
            service.generate_script_from_template("invalid_type", basic_config)

    def test_fallback_script_contains_target_url(
        self, service: K6ScriptService
    ):
        """fallback 脚本应包含目标 URL。"""
        config = K6TestConfig(
            target_url="https://example.com/api",  # type: ignore[arg-type]
            test_type="load",
            script_name="url-test",
        )
        script = service._generate_fallback_script(config)
        assert "https://example.com/api" in script

    def test_fallback_script_contains_vus(
        self, service: K6ScriptService
    ):
        """fallback 脚本应包含 VUs 配置。"""
        config = K6TestConfig(
            target_url="https://example.com",  # type: ignore[arg-type]
            test_type="load",
            vus=50,
        )
        script = service._generate_fallback_script(config)
        assert "50" in script


class TestValidateScriptSyntax:
    """validate_script_syntax 方法测试。"""

    def test_valid_script_passes(self, service: K6ScriptService):
        """有效脚本应通过验证。"""
        script = """
import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  thresholds: {
    http_req_duration: ['p(95)<500'],
  },
};

export default function () {
  http.get('https://httpbin.org/get');
  sleep(1);
}
"""
        result = service.validate_script_syntax(script)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_export_default_fails(self, service: K6ScriptService):
        """缺少 export default function 应验证失败。"""
        script = "import http from 'k6/http';\n// no export default"
        result = service.validate_script_syntax(script)
        assert result.valid is False
        assert any("export default function" in e for e in result.errors)

    def test_missing_http_import_fails(self, service: K6ScriptService):
        """使用 http 但未 import 应验证失败。"""
        script = """
export default function () {
  http.get('https://example.com');
}
"""
        result = service.validate_script_syntax(script)
        assert result.valid is False
        assert any("k6/http" in e for e in result.errors)

    def test_missing_sleep_warning(self, service: K6ScriptService):
        """缺少 sleep 应产生警告（非错误）。"""
        script = """
import http from 'k6/http';
export const options = { thresholds: {} };
export default function () {
  http.get('https://example.com');
}
"""
        result = service.validate_script_syntax(script)
        # sleep 缺失是警告，不是错误
        assert any("sleep" in w.lower() for w in result.warnings)

    def test_missing_thresholds_warning(self, service: K6ScriptService):
        """缺少 thresholds 应产生警告。"""
        script = """
import http from 'k6/http';
import { sleep } from 'k6';
export default function () {
  http.get('https://example.com');
  sleep(1);
}
"""
        result = service.validate_script_syntax(script)
        assert any("threshold" in w.lower() for w in result.warnings)


class TestExtractScriptMetadata:
    """extract_script_metadata 方法测试。"""

    def test_extract_vus(self, service: K6ScriptService):
        """应正确提取 VUs 配置。"""
        script = "export const options = { vus: 25, duration: '1m' };"
        meta = service.extract_script_metadata(script)
        assert meta.vus == 25

    def test_extract_duration(self, service: K6ScriptService):
        """应正确提取 duration 配置。"""
        script = "export const options = { duration: '5m' };"
        meta = service.extract_script_metadata(script)
        assert meta.duration == "5m"

    def test_extract_env_vars(self, service: K6ScriptService):
        """应正确提取 __ENV 变量引用。"""
        script = """
const url = __ENV.K6_BASE_URL;
const vus = __ENV.K6_VUS;
const name = __ENV.K6_TEST_NAME;
"""
        meta = service.extract_script_metadata(script)
        assert "K6_BASE_URL" in meta.env_vars
        assert "K6_VUS" in meta.env_vars
        assert "K6_TEST_NAME" in meta.env_vars


class TestOptimizeThresholds:
    """optimize_thresholds 方法测试。"""

    def test_optimize_p95_threshold(self, service: K6ScriptService):
        """应根据实测 p95 优化阈值。"""
        script = "thresholds: { http_req_duration: ['p(95)<500'] }"
        report = {"http_req_duration_p95": 400.0, "http_req_failed_rate": 0.002}
        optimized = service.optimize_thresholds(script, report)
        # 新 p95 阈值应为 400 * 1.1 = 440
        assert "'p(95)<440'" in optimized

    def test_zero_p95_uses_default(self, service: K6ScriptService):
        """p95 为 0 时应使用默认值 500。"""
        script = "thresholds: { http_req_duration: ['p(95)<500'] }"
        report = {"http_req_duration_p95": 0.0, "http_req_failed_rate": 0.0}
        optimized = service.optimize_thresholds(script, report)
        assert "'p(95)<500'" in optimized
