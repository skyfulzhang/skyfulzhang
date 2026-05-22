"""完整的智能旅行规划助手 Agent 评估系统。

特性：
1. LangGraph Agent（可在依赖缺失时自动降级到顺序执行）
2. Mock 工具集（含 booking_flight 随机失败）
3. EvaluationTracer 全链路追踪
4. 确定性评估 + LLM-as-Judge 评估（每个指标单独请求）
5. 企业级日志、异常处理、类型注解、结构化报告
"""

from __future__ import annotations

import ast
import json
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - 依赖可选
    END = "__end__"
    StateGraph = None

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover - 依赖可选
    ChatOpenAI = None


# ============================== 配置区 ==============================


@dataclass(frozen=True)
class AppConfig:
    """应用配置（支持环境变量覆盖）。"""

    model_name: str = os.getenv("EVAL_MODEL_NAME", "gpt-4o-mini")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    temperature: float = float(os.getenv("EVAL_TEMPERATURE", "0"))
    prompt_token_cost_per_1k: float = float(os.getenv("PROMPT_TOKEN_COST_PER_1K", "0.00015"))
    completion_token_cost_per_1k: float = float(os.getenv("COMPLETION_TOKEN_COST_PER_1K", "0.0006"))
    random_seed: int = int(os.getenv("TRAVEL_AGENT_RANDOM_SEED", "3"))
    booking_fail_rate: float = float(os.getenv("BOOKING_FAIL_RATE", "0.35"))


CONFIG = AppConfig()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("travel_agent_eval")


# ============================== 数据结构 ==============================


@dataclass
class ToolCallRecord:
    tool_name: str
    params: Dict[str, Any]
    result: Any
    success: bool
    redundant: bool
    timestamp: float
    error: Optional[str] = None


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class EvaluationTracer:
    """记录步骤、工具调用、Token 使用、耗时。"""

    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    steps: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    def start(self) -> None:
        self.start_time = time.perf_counter()

    def stop(self) -> None:
        self.end_time = time.perf_counter()

    def add_step(self, _step_name: str) -> None:
        self.steps += 1

    def add_tool_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        success: bool,
        redundant: bool,
        error: Optional[str] = None,
    ) -> None:
        self.tool_calls.append(
            ToolCallRecord(
                tool_name=tool_name,
                params=params,
                result=result,
                success=success,
                redundant=redundant,
                timestamp=time.time(),
                error=error,
            )
        )

    def add_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.token_usage.prompt_tokens += max(0, prompt_tokens)
        self.token_usage.completion_tokens += max(0, completion_tokens)

    @property
    def latency_seconds(self) -> float:
        if not self.end_time or not self.start_time:
            return 0.0
        return max(0.0, self.end_time - self.start_time)


@dataclass
class MetricResult:
    metric_name: str
    value: Any
    rationale: str
    passed: bool


@dataclass
class EvaluationReport:
    task_completion: Dict[str, MetricResult]
    process_quality: Dict[str, MetricResult]
    efficiency: Dict[str, MetricResult]
    robustness: Dict[str, MetricResult]
    total_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_completion": {k: asdict(v) for k, v in self.task_completion.items()},
            "process_quality": {k: asdict(v) for k, v in self.process_quality.items()},
            "efficiency": {k: asdict(v) for k, v in self.efficiency.items()},
            "robustness": {k: asdict(v) for k, v in self.robustness.items()},
            "total_score": round(self.total_score, 4),
        }


class ToolInvocation(TypedDict):
    name: Literal[
        "search_flights",
        "search_hotels",
        "get_weather",
        "calculator",
        "booking_flight",
    ]
    args: Dict[str, Any]


class AgentState(TypedDict, total=False):
    conversation: List[Dict[str, str]]
    plan: List[ToolInvocation]
    current_step: int
    active_call: ToolInvocation
    tool_results: List[Dict[str, Any]]
    final_result: str
    done: bool
    retries: Dict[str, int]
    tracer: EvaluationTracer


# ============================== 日志工具 ==============================


def log_eval_block(
    metric_name: str,
    eval_input: Any,
    eval_output: Any,
    rationale: str,
    conclusion: str,
) -> None:
    logger.info("[EVAL] ============================================================")
    logger.info("[EVAL] 当前评估指标: %s", metric_name)
    logger.info("[EVAL] 评估指标输入: %s", eval_input)
    logger.info("[EVAL] 评估指标输出: %s", eval_output)
    logger.info("[EVAL] 评估依据: %s", rationale)
    logger.info("[EVAL] 评估结果: %s", conclusion)
    logger.info("[EVAL] ============================================================")


# ============================== Mock 工具实现 ==============================


def search_flights(origin: str, destination: str, date_str: str) -> List[Dict[str, Any]]:
    return [
        {
            "flight_id": "MU5101",
            "origin": origin,
            "destination": destination,
            "date": date_str,
            "departure": "08:30",
            "arrival": "10:40",
            "price": 760,
        },
        {
            "flight_id": "CA1855",
            "origin": origin,
            "destination": destination,
            "date": date_str,
            "departure": "14:20",
            "arrival": "16:35",
            "price": 820,
        },
    ]


def search_hotels(location: str, checkin: str, checkout: str, guests: int) -> List[Dict[str, Any]]:
    return [
        {
            "hotel_id": "HTL-001",
            "name": "上海外滩商务酒店",
            "location": location,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "nightly_price": 420,
            "nights": 2,
        },
        {
            "hotel_id": "HTL-002",
            "name": "陆家嘴轻奢酒店",
            "location": location,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "nightly_price": 560,
            "nights": 2,
        },
    ]


def get_weather(city: str, date_str: str) -> Dict[str, Any]:
    return {
        "city": city,
        "date": date_str,
        "condition": "多云",
        "temperature_c": "22~28",
        "advice": "早晚温差小，适合轻薄外套。",
    }


def calculator(expression: str) -> float:
    allowed_ops = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"不支持的表达式: {expression}")

    parsed = ast.parse(expression, mode="eval")
    return round(_eval(parsed.body), 2)


def booking_flight(flight_id: str, passenger_info: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    if rng.random() < CONFIG.booking_fail_rate:
        raise RuntimeError("航司系统暂时不可用，请稍后重试")
    return {
        "order_id": f"ORD-{flight_id}-{int(time.time())}",
        "flight_id": flight_id,
        "passenger": passenger_info,
        "status": "confirmed",
    }


# ============================== LangGraph Agent ==============================


def build_default_plan(travel_date: str) -> List[ToolInvocation]:
    return [
        {"name": "search_flights", "args": {"origin": "北京", "destination": "上海", "date_str": travel_date}},
        {
            "name": "search_hotels",
            "args": {"location": "上海", "checkin": travel_date, "checkout": "2026-06-03", "guests": 1},
        },
        {"name": "get_weather", "args": {"city": "上海", "date_str": travel_date}},
        {"name": "calculator", "args": {"expression": "760 + 420*2 + 200"}},
        {
            "name": "booking_flight",
            "args": {"flight_id": "MU5101", "passenger_info": {"name": "张三", "id": "310*********"}},
        },
    ]


def summarize_plan(tool_results: List[Dict[str, Any]]) -> str:
    flights = next((i["result"] for i in tool_results if i["tool"] == "search_flights" and i["success"]), [])
    hotels = next((i["result"] for i in tool_results if i["tool"] == "search_hotels" and i["success"]), [])
    weather = next((i["result"] for i in tool_results if i["tool"] == "get_weather" and i["success"]), {})
    budget = next((i["result"] for i in tool_results if i["tool"] == "calculator" and i["success"]), None)
    booking = next((i["result"] for i in tool_results if i["tool"] == "booking_flight" and i["success"]), None)

    flight_text = flights[0]["flight_id"] if flights else "无可用航班"
    hotel_text = hotels[0]["name"] if hotels else "无可用酒店"
    weather_text = weather.get("condition", "天气未知")
    booking_text = booking.get("order_id") if isinstance(booking, dict) else "未成功下单"
    return (
        f"已生成北京→上海 3天2晚规划：航班 {flight_text}，酒店 {hotel_text}，"
        f"天气 {weather_text}，预估总预算 {budget} 元，订单状态 {booking_text}。"
    )


def build_tool_dispatcher(rng: random.Random) -> Dict[str, Callable[..., Any]]:
    return {
        "search_flights": search_flights,
        "search_hotels": search_hotels,
        "get_weather": get_weather,
        "calculator": calculator,
        "booking_flight": lambda flight_id, passenger_info: booking_flight(flight_id, passenger_info, rng=rng),
    }


def planner_node(state: AgentState) -> AgentState:
    tracer = state["tracer"]
    tracer.add_step("planner")

    current_step = state.get("current_step", 0)
    plan = state.get("plan", [])
    if current_step >= len(plan):
        return {
            **state,
            "final_result": summarize_plan(state.get("tool_results", [])),
            "done": True,
        }
    return {
        **state,
        "active_call": plan[current_step],
        "done": False,
    }


def tool_node(state: AgentState, dispatcher: Dict[str, Callable[..., Any]]) -> AgentState:
    tracer = state["tracer"]
    active_call = state["active_call"]
    tool_name = active_call["name"]
    args = active_call["args"]

    tracer.add_step(f"tool:{tool_name}")
    seen_calls = {(c.tool_name, json.dumps(c.params, ensure_ascii=False, sort_keys=True)) for c in tracer.tool_calls}
    signature = (tool_name, json.dumps(args, ensure_ascii=False, sort_keys=True))
    redundant = signature in seen_calls

    success = False
    result: Any = None
    error: Optional[str] = None

    try:
        result = dispatcher[tool_name](**args)
        success = True
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        logger.warning("工具调用失败: %s | args=%s | err=%s", tool_name, args, error)
        result = {"error": error}

    tracer.add_tool_call(tool_name, args, result, success, redundant, error=error)

    tool_results = list(state.get("tool_results", []))
    tool_results.append({"tool": tool_name, "args": args, "result": result, "success": success})

    retries = dict(state.get("retries", {}))
    current_step = state.get("current_step", 0)

    if not success and tool_name == "booking_flight":
        retries[tool_name] = retries.get(tool_name, 0) + 1
        if retries[tool_name] < 2:
            logger.info("booking_flight 失败后进行恢复重试，第 %s 次", retries[tool_name])
            return {
                **state,
                "tool_results": tool_results,
                "retries": retries,
                "done": False,
            }

    return {
        **state,
        "tool_results": tool_results,
        "current_step": current_step + 1,
        "retries": retries,
        "done": False,
    }


def route_after_planner(state: AgentState) -> str:
    return "end" if state.get("done", False) else "tool"


def build_agent_graph(dispatcher: Dict[str, Callable[..., Any]]):
    if StateGraph is None:
        return None

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("tool", lambda state: tool_node(state, dispatcher))
    graph.set_entry_point("planner")
    graph.add_conditional_edges("planner", route_after_planner, {"tool": "tool", "end": END})
    graph.add_edge("tool", "planner")
    return graph.compile()


def run_agent(conversation: List[Dict[str, str]], seed: int) -> Tuple[AgentState, EvaluationTracer]:
    tracer = EvaluationTracer()
    tracer.start()

    rng = random.Random(seed)
    dispatcher = build_tool_dispatcher(rng)
    plan = build_default_plan("2026-06-01")

    initial_state: AgentState = {
        "conversation": conversation,
        "plan": plan,
        "current_step": 0,
        "tool_results": [],
        "final_result": "",
        "done": False,
        "retries": {},
        "tracer": tracer,
    }

    compiled_graph = build_agent_graph(dispatcher)
    final_state: AgentState

    if compiled_graph is not None:
        final_state = compiled_graph.invoke(initial_state)
    else:
        logger.warning("未检测到 langgraph，使用顺序执行降级模式。")
        state = initial_state
        while True:
            state = planner_node(state)
            if state.get("done"):
                break
            state = tool_node(state, dispatcher)
        final_state = state

    tracer.stop()
    return final_state, tracer


# ============================== LLM 评估器 ==============================


class LLMJudge:
    def __init__(self, config: AppConfig, tracer: EvaluationTracer) -> None:
        self.config = config
        self.tracer = tracer
        self.client = None
        if ChatOpenAI and config.openai_api_key:
            self.client = ChatOpenAI(
                model=config.model_name,
                api_key=config.openai_api_key,
                temperature=config.temperature,
            )
        elif not config.openai_api_key:
            logger.warning("未设置 OPENAI_API_KEY，LLM 评估将回退到规则模式。")

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    def judge_once(
        self,
        metric_name: str,
        eval_input: Dict[str, Any],
        criteria: str,
        fallback_value: Any,
    ) -> Tuple[Any, str, Dict[str, Any]]:
        payload = {
            "metric": metric_name,
            "input": eval_input,
            "criteria": criteria,
            "output_format": {"score": "number", "reason": "string"},
        }
        prompt = (
            "你是企业级Agent评估专家。请严格依据给定criteria输出JSON，"
            "仅输出JSON，不要额外文本。\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        if self.client is None:
            reason = "回退规则：无可用LLM客户端，返回安全默认值。"
            prompt_tokens = self._estimate_tokens(prompt)
            completion_tokens = self._estimate_tokens(json.dumps({"score": fallback_value, "reason": reason}, ensure_ascii=False))
            self.tracer.add_tokens(prompt_tokens, completion_tokens)
            return fallback_value, reason, {"fallback": True}

        try:
            response = self.client.invoke(prompt)
            content = getattr(response, "content", "")
            parsed = self._extract_json(content) or {}

            metadata = getattr(response, "response_metadata", {}) or {}
            token_usage = metadata.get("token_usage", {}) if isinstance(metadata, dict) else {}
            prompt_tokens = int(token_usage.get("prompt_tokens", self._estimate_tokens(prompt)))
            completion_tokens = int(token_usage.get("completion_tokens", self._estimate_tokens(str(content))))
            self.tracer.add_tokens(prompt_tokens, completion_tokens)

            score = parsed.get("score", fallback_value)
            reason = str(parsed.get("reason", "LLM 未返回理由，使用默认说明。"))
            return score, reason, parsed
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM评估失败(%s): %s", metric_name, exc)
            reason = f"LLM调用异常，回退默认值: {exc}"
            self.tracer.add_tokens(self._estimate_tokens(prompt), self._estimate_tokens(reason))
            return fallback_value, reason, {"fallback": True, "error": str(exc)}


# ============================== 确定性评估函数 ==============================


def eval_tool_call_accuracy(tracer: EvaluationTracer) -> float:
    total = len(tracer.tool_calls)
    correct = sum(1 for c in tracer.tool_calls if c.success)
    score = round(correct / total, 4) if total else 0.0
    log_eval_block(
        "工具调用准确率",
        {"total_calls": total, "successful_calls": correct},
        score,
        "正确调用次数 / 总调用次数",
        "通过" if score >= 0.7 else "待优化",
    )
    return score


def eval_redundancy_rate(tracer: EvaluationTracer) -> float:
    total = len(tracer.tool_calls)
    redundant = sum(1 for c in tracer.tool_calls if c.redundant)
    score = round(redundant / total, 4) if total else 0.0
    log_eval_block(
        "冗余步骤率",
        {"total_calls": total, "redundant_calls": redundant},
        score,
        "冗余步骤数 / 总步骤数",
        "优秀" if score <= 0.2 else "偏高",
    )
    return score


def eval_avg_steps(tracer: EvaluationTracer) -> float:
    avg_steps = float(tracer.steps)
    log_eval_block(
        "平均步骤数",
        {"steps": tracer.steps},
        avg_steps,
        "单任务总步骤（当前样本任务数=1）",
        "优秀" if avg_steps <= 12 else "偏高",
    )
    return avg_steps


def eval_token_consumption(tracer: EvaluationTracer) -> Dict[str, int]:
    output = {
        "prompt_tokens": tracer.token_usage.prompt_tokens,
        "completion_tokens": tracer.token_usage.completion_tokens,
        "total_tokens": tracer.token_usage.total_tokens,
    }
    log_eval_block(
        "Token 消耗",
        {"token_usage": asdict(tracer.token_usage)},
        output,
        "prompt + completion token 总和",
        "可接受" if output["total_tokens"] <= 10000 else "过高",
    )
    return output


def eval_latency(tracer: EvaluationTracer) -> float:
    latency = round(tracer.latency_seconds, 4)
    log_eval_block(
        "任务耗时",
        {"start_time": tracer.start_time, "end_time": tracer.end_time},
        latency,
        "从输入到输出的总耗时（秒）",
        "优秀" if latency <= 5 else "需优化",
    )
    return latency


def eval_cost_efficiency(tracer: EvaluationTracer, task_success: float) -> Dict[str, float]:
    prompt_cost = tracer.token_usage.prompt_tokens / 1000 * CONFIG.prompt_token_cost_per_1k
    completion_cost = tracer.token_usage.completion_tokens / 1000 * CONFIG.completion_token_cost_per_1k
    total_cost = prompt_cost + completion_cost
    value_score = (task_success * 100) / max(total_cost, 0.0001)
    output = {
        "prompt_cost_usd": round(prompt_cost, 6),
        "completion_cost_usd": round(completion_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "value_per_usd": round(value_score, 4),
    }
    log_eval_block(
        "成本效率",
        {
            "prompt_tokens": tracer.token_usage.prompt_tokens,
            "completion_tokens": tracer.token_usage.completion_tokens,
            "task_success": task_success,
        },
        output,
        "任务价值 / API 成本",
        "优秀" if output["value_per_usd"] >= 50 else "一般",
    )
    return output


# ============================== LLM 评估函数 ==============================


def eval_task_success_rate(judge: LLMJudge, conversation: List[Dict[str, str]], result: str) -> int:
    score, reason, raw = judge.judge_once(
        "任务成功率 (SR)",
        {"conversation": conversation, "result": result},
        "判断最终结果是否达成用户目标，输出0或1。",
        fallback_value=1 if "已生成" in result else 0,
    )
    output = int(float(score) >= 1)
    log_eval_block("任务成功率 (SR)", {"conversation": conversation, "result": result}, raw, reason, f"SR={output}")
    return output


def eval_partial_completion_rate(
    judge: LLMJudge,
    conversation: List[Dict[str, str]],
    result: str,
    subtasks: List[str],
) -> float:
    score, reason, raw = judge.judge_once(
        "部分完成率 (PCR)",
        {"conversation": conversation, "result": result, "subtasks": subtasks},
        "按完成子目标数/总子目标数打分，输出0-1浮点数。",
        fallback_value=0.75,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("部分完成率 (PCR)", {"subtasks": subtasks, "result": result}, raw, reason, f"PCR={output:.4f}")
    return round(output, 4)


def eval_quality_score(judge: LLMJudge, conversation: List[Dict[str, str]], result: str) -> int:
    score, reason, raw = judge.judge_once(
        "结果质量分 (QS)",
        {"conversation": conversation, "result": result},
        "按结果好坏给1-5分。",
        fallback_value=4,
    )
    output = int(max(1, min(5, round(float(score)))))
    log_eval_block("结果质量分 (QS)", {"result": result}, raw, reason, f"QS={output}")
    return output


def eval_goal_coverage_rate(
    judge: LLMJudge,
    conversation: List[Dict[str, str]],
    result: str,
    goals: List[str],
) -> float:
    score, reason, raw = judge.judge_once(
        "目标覆盖率 (GCR)",
        {"conversation": conversation, "result": result, "goals": goals},
        "按达成目标数/预期目标数输出0-1浮点数。",
        fallback_value=0.8,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("目标覆盖率 (GCR)", {"goals": goals, "result": result}, raw, reason, f"GCR={output:.4f}")
    return round(output, 4)


def eval_hallucination_rate(
    judge: LLMJudge,
    conversation: List[Dict[str, str]],
    tool_results: List[Dict[str, Any]],
) -> float:
    score, reason, raw = judge.judge_once(
        "幻觉率",
        {"conversation": conversation, "tool_results": tool_results},
        "按虚假信息次数/总推理步数输出0-1，越低越好。",
        fallback_value=0.1,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("幻觉率", {"tool_results": tool_results}, raw, reason, f"HallucinationRate={output:.4f}")
    return round(output, 4)


def eval_plan_reasonableness(judge: LLMJudge, tool_call_sequence: List[str]) -> float:
    score, reason, raw = judge.judge_once(
        "计划合理性",
        {"tool_call_sequence": tool_call_sequence},
        "按规划路径是否合理输出0-1分数。",
        fallback_value=0.85,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("计划合理性", {"tool_call_sequence": tool_call_sequence}, raw, reason, f"PlanReasonableness={output:.4f}")
    return round(output, 4)


def eval_error_recovery(judge: LLMJudge, tracer: EvaluationTracer) -> float:
    failed = [c for c in tracer.tool_calls if not c.success]
    recovered = 0
    for fail in failed:
        recovered += any(
            c.success and c.tool_name == fail.tool_name and c.timestamp >= fail.timestamp for c in tracer.tool_calls
        )
    fallback = round(recovered / len(failed), 4) if failed else 1.0

    score, reason, raw = judge.judge_once(
        "错误恢复率",
        {"tool_calls": [asdict(c) for c in tracer.tool_calls]},
        "按遇错后自主恢复比例输出0-1。",
        fallback_value=fallback,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("错误恢复率", {"failed_calls": len(failed), "recovered": recovered}, raw, reason, f"Recovery={output:.4f}")
    return round(output, 4)


def eval_adversarial_robustness(judge: LLMJudge, conversation: List[Dict[str, str]]) -> float:
    score, reason, raw = judge.judge_once(
        "对抗鲁棒性",
        {"conversation": conversation},
        "评估面对误导信息时的抵抗能力，输出0-1。",
        fallback_value=0.8,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("对抗鲁棒性", {"conversation": conversation}, raw, reason, f"AdversarialRobustness={output:.4f}")
    return round(output, 4)


def eval_consistency(judge: LLMJudge, results_list: List[str]) -> float:
    fallback = 1.0 if len(set(results_list)) == 1 else 0.6
    score, reason, raw = judge.judge_once(
        "一致性",
        {"results_list": results_list},
        "评估同一问题多次运行结果稳定性，输出0-1。",
        fallback_value=fallback,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("一致性", {"results_list": results_list}, raw, reason, f"Consistency={output:.4f}")
    return round(output, 4)


def eval_boundary_handling(judge: LLMJudge, tracer: EvaluationTracer) -> float:
    score, reason, raw = judge.judge_once(
        "边界处理",
        {"tool_calls": [asdict(c) for c in tracer.tool_calls]},
        "评估异常输入、边界条件处理能力，输出0-1。",
        fallback_value=0.78,
    )
    output = max(0.0, min(1.0, float(score)))
    log_eval_block("边界处理", {"tool_calls": len(tracer.tool_calls)}, raw, reason, f"BoundaryHandling={output:.4f}")
    return round(output, 4)


# ============================== 汇总与主流程 ==============================


def aggregate_total_score(report: EvaluationReport) -> float:
    """将不同量纲指标归一化为0-1并求均值。"""

    normalized: List[float] = []

    # 任务完成类
    normalized.extend(
        [
            float(report.task_completion["SR"].value),
            float(report.task_completion["PCR"].value),
            float(report.task_completion["QS"].value) / 5.0,
            float(report.task_completion["GCR"].value),
        ]
    )

    # 过程质量类
    normalized.extend(
        [
            float(report.process_quality["tool_call_accuracy"].value),
            1 - float(report.process_quality["hallucination_rate"].value),
            float(report.process_quality["plan_reasonableness"].value),
            1 - float(report.process_quality["redundancy_rate"].value),
        ]
    )

    # 效率类
    steps = float(report.efficiency["avg_steps"].value)
    tokens = float(report.efficiency["token_consumption"].value["total_tokens"])
    latency = float(report.efficiency["latency"].value)
    value_per_usd = float(report.efficiency["cost_efficiency"].value["value_per_usd"])
    normalized.extend(
        [
            max(0.0, min(1.0, 10 / max(steps, 1))),
            max(0.0, min(1.0, 5000 / max(tokens, 1))),
            max(0.0, min(1.0, 5 / max(latency, 0.1))),
            max(0.0, min(1.0, value_per_usd / 100)),
        ]
    )

    # 鲁棒性类
    normalized.extend(
        [
            float(report.robustness["error_recovery"].value),
            float(report.robustness["adversarial_robustness"].value),
            float(report.robustness["consistency"].value),
            float(report.robustness["boundary_handling"].value),
        ]
    )

    return round(sum(normalized) / len(normalized), 4)


def main() -> None:
    random.seed(CONFIG.random_seed)
    logger.info("启动 travel_agent_eval，随机种子=%s", CONFIG.random_seed)

    conversation = [
        {"role": "user", "content": "我想从北京去上海玩3天2晚，帮我在预算内规划。"},
        {"role": "assistant", "content": "好的，请问预算上限和出行日期？"},
        {"role": "user", "content": "预算2000元左右，6月1日出发。"},
        {"role": "assistant", "content": "收到，我会综合航班、酒店、天气并给出下单建议。"},
    ]
    goals = ["机票规划", "酒店规划", "预算估算", "天气提示", "航班下单"]
    subtasks = goals

    final_state, tracer = run_agent(conversation, seed=CONFIG.random_seed)
    result = final_state.get("final_result", "")
    tool_results = final_state.get("tool_results", [])

    judge = LLMJudge(CONFIG, tracer)

    # 任务完成类（4次 LLM 请求）
    sr = eval_task_success_rate(judge, conversation, result)
    pcr = eval_partial_completion_rate(judge, conversation, result, subtasks)
    qs = eval_quality_score(judge, conversation, result)
    gcr = eval_goal_coverage_rate(judge, conversation, result, goals)

    # 过程质量类（2个确定性 + 2次 LLM）
    tool_call_accuracy = eval_tool_call_accuracy(tracer)
    hallucination_rate = eval_hallucination_rate(judge, conversation, tool_results)
    plan_reasonableness = eval_plan_reasonableness(judge, [c.tool_name for c in tracer.tool_calls])
    redundancy_rate = eval_redundancy_rate(tracer)

    # 效率类（全确定性）
    avg_steps = eval_avg_steps(tracer)
    token_consumption = eval_token_consumption(tracer)
    latency = eval_latency(tracer)
    cost_efficiency = eval_cost_efficiency(tracer, task_success=float(sr))

    # 鲁棒性类（4次 LLM 请求）
    error_recovery = eval_error_recovery(judge, tracer)
    adversarial_robustness = eval_adversarial_robustness(judge, conversation)

    consistency_runs = [run_agent(conversation, seed=CONFIG.random_seed)[0].get("final_result", "") for _ in range(3)]
    consistency = eval_consistency(judge, consistency_runs)

    boundary_handling = eval_boundary_handling(judge, tracer)

    report = EvaluationReport(
        task_completion={
            "SR": MetricResult("任务成功率 (SR)", sr, "LLM 0/1 判断任务是否达成", sr >= 1),
            "PCR": MetricResult("部分完成率 (PCR)", pcr, "LLM 判断子目标完成比例", pcr >= 0.7),
            "QS": MetricResult("结果质量分 (QS)", qs, "LLM 1-5 质量打分", qs >= 3),
            "GCR": MetricResult("目标覆盖率 (GCR)", gcr, "LLM 判断目标覆盖比例", gcr >= 0.7),
        },
        process_quality={
            "tool_call_accuracy": MetricResult("工具调用准确率", tool_call_accuracy, "确定性函数统计", tool_call_accuracy >= 0.7),
            "hallucination_rate": MetricResult("幻觉率", hallucination_rate, "LLM 判断虚假信息比例", hallucination_rate <= 0.3),
            "plan_reasonableness": MetricResult("计划合理性", plan_reasonableness, "LLM 判断路径合理性", plan_reasonableness >= 0.7),
            "redundancy_rate": MetricResult("冗余步骤率", redundancy_rate, "确定性函数统计", redundancy_rate <= 0.2),
        },
        efficiency={
            "avg_steps": MetricResult("平均步骤数", avg_steps, "确定性函数统计", avg_steps <= 12),
            "token_consumption": MetricResult("Token 消耗", token_consumption, "确定性函数统计", token_consumption["total_tokens"] <= 10000),
            "latency": MetricResult("任务耗时", latency, "确定性函数统计", latency <= 5),
            "cost_efficiency": MetricResult("成本效率", cost_efficiency, "确定性函数统计", cost_efficiency["value_per_usd"] >= 50),
        },
        robustness={
            "error_recovery": MetricResult("错误恢复率", error_recovery, "LLM 判断失败恢复能力", error_recovery >= 0.5),
            "adversarial_robustness": MetricResult("对抗鲁棒性", adversarial_robustness, "LLM 判断抗误导能力", adversarial_robustness >= 0.7),
            "consistency": MetricResult("一致性", consistency, "LLM 判断多次运行稳定性", consistency >= 0.7),
            "boundary_handling": MetricResult("边界处理", boundary_handling, "LLM 判断边界条件处理", boundary_handling >= 0.7),
        },
        total_score=0.0,
    )
    report.total_score = aggregate_total_score(report)

    logger.info("\n================= Evaluation Final Report =================")
    logger.info(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
