"""
agent/tools/k6_script_tools.py
k6 脚本生成与验证工具集 - LangChain StructuredTool 封装。
"""

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.models.test_config import K6TestConfig
from agent.services.k6_service import K6ScriptService
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_k6_service = K6ScriptService()


# ── Input Schema Models ───────────────────────────────────────────────────────

class GenerateScriptInput(BaseModel):
    """生成 k6 脚本的输入参数。"""
    target_url: str = Field(description="被测目标 URL，如 https://api.example.com")
    test_type: str = Field(
        default="load",
        description="测试类型: load/stress/spike/soak/api",
    )
    vus: int = Field(default=10, description="并发虚拟用户数（1-10000）")
    duration: str = Field(default="30s", description="稳定期时长，如 30s/5m/1h")
    ramp_up_time: str = Field(default="10s", description="爬升期时长")
    ramp_down_time: str = Field(default="10s", description="下降期时长")
    script_name: str = Field(default="test", description="脚本名称")
    description: str = Field(default="", description="测试描述")


class ValidateScriptInput(BaseModel):
    """验证 k6 脚本的输入参数。"""
    script_content: str = Field(description="k6 JavaScript 脚本内容")


class OptimizeThresholdsInput(BaseModel):
    """优化阈值的输入参数。"""
    current_script: str = Field(description="当前 k6 脚本内容")
    p95_ms: float = Field(description="实测 p95 响应时间（ms）")
    error_rate: float = Field(description="实测错误率（0~1 之间）")


class GetTemplateInput(BaseModel):
    """获取模板的输入参数。"""
    test_type: str = Field(
        description="测试类型: load/stress/spike/soak/api",
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

def _generate_k6_script(
    target_url: str,
    test_type: str = "load",
    vus: int = 10,
    duration: str = "30s",
    ramp_up_time: str = "10s",
    ramp_down_time: str = "10s",
    script_name: str = "test",
    description: str = "",
) -> str:
    """根据配置生成 k6 测试脚本。"""
    try:
        config = K6TestConfig(
            target_url=target_url,  # type: ignore[arg-type]
            test_type=test_type,  # type: ignore[arg-type]
            vus=vus,
            duration=duration,
            ramp_up_time=ramp_up_time,
            ramp_down_time=ramp_down_time,
            script_name=script_name,
            description=description,
        )
        script = _k6_service.generate_script_from_template(test_type, config)
        # 验证生成的脚本
        result = _k6_service.validate_script_syntax(script)
        warnings_str = ""
        if result.warnings:
            warnings_str = f"\n⚠️ 警告：{', '.join(result.warnings)}"
        return f"✅ 脚本生成成功！{warnings_str}\n\n```javascript\n{script}\n```"
    except Exception as exc:
        logger.error("generate_script_error", error=str(exc))
        return f"❌ 脚本生成失败: {exc!s}"


generate_k6_script_tool = StructuredTool.from_function(
    func=_generate_k6_script,
    name="generate_k6_script",
    description=(
        "根据用户配置（URL、测试类型、VUs、时长）生成 k6 性能测试脚本。"
        "这是创建新测试的第一步。"
        "生成后需要验证语法，然后上传到 GitHub 仓库。"
        "测试类型: load（正常负载）/ stress（压力）/ spike（尖峰）/ soak（浸泡）/ api（API 功能+性能）"
    ),
    args_schema=GenerateScriptInput,
)


def _validate_k6_script(script_content: str) -> str:
    """验证 k6 脚本语法。"""
    try:
        result = _k6_service.validate_script_syntax(script_content)
        if result.valid:
            warnings_str = (
                f"\n⚠️ 建议修改：\n" + "\n".join(f"  - {w}" for w in result.warnings)
                if result.warnings
                else ""
            )
            return f"✅ 语法验证通过！{warnings_str}"
        else:
            errors_str = "\n".join(f"  ❌ {e}" for e in result.errors)
            warnings_str = (
                "\n".join(f"  ⚠️ {w}" for w in result.warnings)
                if result.warnings
                else ""
            )
            return (
                f"❌ 语法验证失败！\n错误：\n{errors_str}"
                + (f"\n警告：\n{warnings_str}" if warnings_str else "")
            )
    except Exception as exc:
        return f"❌ 验证失败: {exc!s}"


validate_k6_script_tool = StructuredTool.from_function(
    func=_validate_k6_script,
    name="validate_k6_script",
    description=(
        "对 k6 JavaScript 脚本进行静态语法检查。"
        "上传脚本前应先验证，确保脚本格式正确。"
        "会检查：export default function、import 语句、options 配置、sleep 调用等。"
    ),
    args_schema=ValidateScriptInput,
)


def _optimize_script_thresholds(
    current_script: str,
    p95_ms: float,
    error_rate: float,
) -> str:
    """根据实测数据优化脚本阈值。"""
    try:
        report_data = {"http_req_duration_p95": p95_ms, "http_req_failed_rate": error_rate}
        optimized = _k6_service.optimize_thresholds(current_script, report_data)
        return f"✅ 阈值已优化！\n\n```javascript\n{optimized}\n```"
    except Exception as exc:
        return f"❌ 优化阈值失败: {exc!s}"


optimize_script_thresholds_tool = StructuredTool.from_function(
    func=_optimize_script_thresholds,
    name="optimize_script_thresholds",
    description=(
        "根据历史测试报告数据，智能调整 k6 脚本中的性能阈值。"
        "输入实测 p95 响应时间和错误率，自动建议合理的阈值配置。"
        "适合在测试稳定后收紧阈值，或在测试失败后放宽阈值。"
    ),
    args_schema=OptimizeThresholdsInput,
)


def _get_script_template(test_type: str) -> str:
    """获取指定类型的原始模板内容。"""
    try:
        from pathlib import Path

        template_map = {
            "load": "http_load_test.js",
            "stress": "stress_test.js",
            "spike": "spike_test.js",
            "soak": "soak_test.js",
            "api": "api_test.js",
        }
        if test_type not in template_map:
            return (
                f"❌ 不支持的测试类型: {test_type!r}，"
                f"可选: {list(template_map.keys())}"
            )

        template_file = (
            Path(__file__).parent.parent.parent
            / "k6_scripts"
            / "templates"
            / template_map[test_type]
        )

        if not template_file.exists():
            return f"❌ 模板文件不存在: {template_file}"

        content = template_file.read_text(encoding="utf-8")
        return f"✅ {test_type} 模板内容：\n\n```javascript\n{content}\n```"
    except Exception as exc:
        return f"❌ 获取模板失败: {exc!s}"


get_script_template_tool = StructuredTool.from_function(
    func=_get_script_template,
    name="get_script_template",
    description=(
        "获取指定类型的原始 k6 脚本模板内容。"
        "用于查看标准模板，或作为自定义脚本的参考。"
        "类型: load / stress / spike / soak / api"
    ),
    args_schema=GetTemplateInput,
)


def get_k6_script_tools() -> list[BaseTool]:
    """返回所有 k6 脚本工具列表。"""
    return [
        generate_k6_script_tool,
        validate_k6_script_tool,
        optimize_script_thresholds_tool,
        get_script_template_tool,
    ]
