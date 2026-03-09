"""
agent/services/k6_service.py
k6 脚本模板服务 - 提供脚本生成、验证和优化功能。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent.models.test_config import K6TestConfig
from agent.utils.logger import get_logger

logger = get_logger(__name__)

# 模板目录（相对于本文件的上两级目录下的 k6_scripts/templates）
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "k6_scripts" / "templates"


@dataclass
class ValidationResult:
    """脚本语法验证结果。"""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScriptMetadata:
    """k6 脚本元数据（从脚本内容提取）。"""

    vus: Optional[int] = None
    duration: Optional[str] = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    thresholds: dict[str, list[str]] = field(default_factory=dict)
    env_vars: list[str] = field(default_factory=list)


class K6ScriptService:
    """k6 脚本模板服务。

    提供从模板生成脚本、静态语法验证、元数据提取和阈值优化等功能。
    """

    #: 支持的测试类型
    TEST_TYPES: list[str] = ["load", "stress", "spike", "soak", "api"]

    def generate_script_from_template(
        self,
        test_type: str,
        config: K6TestConfig,
    ) -> str:
        """根据模板和配置生成 k6 测试脚本。

        Args:
            test_type: 测试类型（load/stress/spike/soak/api）。
            config: 测试配置对象。

        Returns:
            str: 生成的 k6 JavaScript 脚本内容。

        Raises:
            ValueError: 不支持的测试类型或模板文件缺失。
        """
        if test_type not in self.TEST_TYPES:
            raise ValueError(
                f"不支持的测试类型 {test_type!r}，可选: {self.TEST_TYPES}"
            )

        template_map = {
            "load": "http_load_test.js",
            "stress": "stress_test.js",
            "spike": "spike_test.js",
            "soak": "soak_test.js",
            "api": "api_test.js",
        }
        template_file = _TEMPLATES_DIR / template_map[test_type]

        if not template_file.exists():
            # fallback：动态生成基础脚本
            logger.warning(
                "template_not_found_using_fallback",
                template=str(template_file),
                test_type=test_type,
            )
            return self._generate_fallback_script(config)

        template_content = template_file.read_text(encoding="utf-8")
        script = self._substitute_template_vars(template_content, config)

        logger.info(
            "script_generated",
            test_type=test_type,
            script_name=config.script_name,
            template=template_file.name,
        )
        return script

    def _substitute_template_vars(
        self, template: str, config: K6TestConfig
    ) -> str:
        """将模板中的占位符替换为实际配置值。"""
        target_url = str(config.target_url).rstrip("/")

        # 构建 thresholds JS 对象字符串
        thresholds_js = self._dict_to_js_object(
            {k: v for k, v in config.thresholds.items()}
        )

        # 构建 headers JS 对象字符串
        headers_js = self._dict_to_js_object(config.headers)

        vus_str = str(config.vus)
        duration_str = config.duration
        ramp_up_str = config.ramp_up_time
        ramp_down_str = config.ramp_down_time

        replacements = {
            "{{BASE_URL}}": target_url,
            "{{VUS}}": vus_str,
            "{{DURATION}}": duration_str,
            "{{RAMP_UP}}": ramp_up_str,
            "{{RAMP_DOWN}}": ramp_down_str,
            "{{TEST_NAME}}": config.script_name,
            "{{DESCRIPTION}}": config.description,
            "{{THRESHOLDS}}": thresholds_js,
            "{{HEADERS}}": headers_js,
        }

        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result

    def _dict_to_js_object(self, d: dict[str, Any]) -> str:
        """将 Python dict 转换为 JS 对象字面量字符串。"""
        if not d:
            return "{}"
        lines = []
        for k, v in d.items():
            if isinstance(v, list):
                items = ", ".join(f'"{item}"' for item in v)
                lines.append(f'    "{k}": [{items}]')
            elif isinstance(v, str):
                lines.append(f'    "{k}": "{v}"')
            else:
                lines.append(f'    "{k}": {v}')
        return "{\n" + ",\n".join(lines) + "\n  }"

    def _generate_fallback_script(self, config: K6TestConfig) -> str:
        """当模板文件不存在时，动态生成基础 k6 脚本。"""
        target_url = str(config.target_url).rstrip("/")
        vus = config.vus
        duration = config.duration
        ramp_up = config.ramp_up_time
        ramp_down = config.ramp_down_time

        thresholds_entries = []
        for metric, conditions in config.thresholds.items():
            cond_str = ", ".join(f'"{c}"' for c in conditions)
            thresholds_entries.append(f'    "{metric}": [{cond_str}]')
        thresholds_block = "{\n" + ",\n".join(thresholds_entries) + "\n  }" if thresholds_entries else "{}"

        return f"""/**
 * K6 Performance Test - {config.script_name}
 * Test Type: {config.test_type}
 * Description: {config.description}
 * Auto-generated by perf-test-agent
 */
import http from 'k6/http';
import {{ sleep, check }} from 'k6';
import {{ Rate }} from 'k6/metrics';

const errorRate = new Rate('custom_error_rate');
const BASE_URL = __ENV.K6_BASE_URL || '{target_url}';
const TEST_NAME = __ENV.K6_TEST_NAME || '{config.script_name}';

export const options = {{
  stages: [
    {{ duration: '{ramp_up}', target: {vus} }},
    {{ duration: '{duration}', target: {vus} }},
    {{ duration: '{ramp_down}', target: 0 }},
  ],
  thresholds: {thresholds_block},
}};

export default function () {{
  const res = http.get(`${{BASE_URL}}`);

  const ok = check(res, {{
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  }});

  errorRate.add(!ok);
  sleep(1);
}}
"""

    def validate_script_syntax(self, script_content: str) -> ValidationResult:
        """对 k6 脚本进行静态语法检查。

        使用正则表达式进行基础检查（不依赖 Node.js/k6 运行时）。

        Args:
            script_content: k6 JavaScript 脚本内容。

        Returns:
            ValidationResult: 验证结果，包含错误和警告列表。
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 检查必要的 export default function
        if not re.search(r"export\s+default\s+function", script_content):
            errors.append("脚本缺少 `export default function`（k6 主测试函数）")

        # 检查 import http from 'k6/http'（对 HTTP 测试）
        if "http.get" in script_content or "http.post" in script_content:
            if not re.search(r"import\s+http\s+from\s+['\"]k6/http['\"]", script_content):
                errors.append("使用了 http.get/http.post 但未 import 'k6/http'")

        # 检查 options export
        if not re.search(r"export\s+(?:const|let|var)\s+options", script_content):
            warnings.append("未找到 `export const options`，将使用 k6 默认配置")

        # 检查 sleep 调用（防止过度压测）
        if "sleep(" not in script_content:
            warnings.append("脚本中未调用 sleep()，可能导致过度压测")

        # 检查阈值配置
        if "thresholds" not in script_content:
            warnings.append("未配置 thresholds，建议添加性能阈值")

        valid = len(errors) == 0
        logger.debug(
            "script_validated",
            valid=valid,
            errors=len(errors),
            warnings=len(warnings),
        )
        return ValidationResult(valid=valid, errors=errors, warnings=warnings)

    def extract_script_metadata(self, script_content: str) -> ScriptMetadata:
        """从 k6 脚本内容提取关键配置元数据。

        Args:
            script_content: k6 JavaScript 脚本内容。

        Returns:
            ScriptMetadata: 提取的元数据。
        """
        metadata = ScriptMetadata()

        # 提取 VUs（简单模式：options.vus）
        vus_match = re.search(r"vus\s*:\s*(\d+)", script_content)
        if vus_match:
            metadata.vus = int(vus_match.group(1))

        # 提取 duration
        dur_match = re.search(r"duration\s*:\s*['\"](\d+[smh])['\"]", script_content)
        if dur_match:
            metadata.duration = dur_match.group(1)

        # 提取 __ENV 变量引用
        env_refs = re.findall(r"__ENV\.(\w+)", script_content)
        metadata.env_vars = list(set(env_refs))

        logger.debug("metadata_extracted", vus=metadata.vus, duration=metadata.duration)
        return metadata

    def optimize_thresholds(
        self,
        current_script: str,
        report_data: dict[str, Any],
    ) -> str:
        """根据历史报告数据智能调整 k6 脚本中的阈值。

        Args:
            current_script: 当前脚本内容。
            report_data: 历史报告数据（K6ReportSummary 字段字典）。

        Returns:
            str: 调整后的脚本内容。
        """
        p95 = report_data.get("http_req_duration_p95", 0)
        error_rate = report_data.get("http_req_failed_rate", 0)

        # 根据实测 p95 设置略高于实测值的阈值（给 10% 余量）
        suggested_p95 = int(p95 * 1.1) if p95 > 0 else 500
        # 错误率阈值取实测值的 2 倍，最小 0.01
        suggested_error_rate = max(round(error_rate * 2, 4), 0.01)

        optimized = re.sub(
            r"'p\(95\)<\d+'",
            f"'p(95)<{suggested_p95}'",
            current_script,
        )
        optimized = re.sub(
            r"'rate<[\d.]+'",
            f"'rate<{suggested_error_rate}'",
            optimized,
        )

        logger.info(
            "thresholds_optimized",
            suggested_p95=suggested_p95,
            suggested_error_rate=suggested_error_rate,
        )
        return optimized
