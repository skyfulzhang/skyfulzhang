"""智能旅行规划助手 Agent 评估系统（单文件版）。

功能覆盖：
1. LangGraph Agent（含 mock 工具）
2. EvaluationTracer 追踪工具调用/Token/步骤/耗时/错误恢复
3. 确定性指标评估函数
4. LLM-as-Judge 指标评估函数（每个指标独立请求）
5. EvaluationReport 汇总输出
6. main() 演示北京->上海 3天2晚预算内规划场景
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

# -------------------- 第一部分：配置区 --------------------
random.seed(42)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG: Dict[str, Any] = {
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
    "MODEL_NAME": os.getenv("MODEL_NAME", "gpt-4.1-mini"),
    "JUDGE_MODEL": os.getenv("JUDGE_MODEL", "gpt-4.1-mini"),
    "PRICE_PROMPT_PER_1K": float(os.getenv("PRICE_PROMPT_PER_1K", "0.005")),
    "PRICE_COMPLETION_PER_1K": float(os.getenv("PRICE_COMPLETION_PER_1K", "0.015")),
    "MAX_STEPS": int(os.getenv("MAX_STEPS", "12")),
}


# -------------------- 第二部分：Mock 工具实现 --------------------
@tool
def search_flights(origin: str, destination: str, date: str) -> List[Dict[str, Any]]:
    """搜索航班列表（Mock）。"""
    flights = [
        {
            "flight_id": "MU5101",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "08:00",
            "arrive": "10:20",
            "price": 880,
        },
        {
            "flight_id": "CA1833",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "13:30",
            "arrive": "15:45",
            "price": 760,
        },
        {
            "flight_id": "HO1259",
            "origin": origin,
            "destination": destination,
            "date": date,
            "depart": "19:10",
            "arrive": "21:30",
            "price": 699,
        },
    ]
    return flights


@tool
def search_hotels(location: str, checkin: str, checkout: str, guests: int) -> List[Dict[str, Any]]:
    """搜索酒店列表（Mock）。"""
    hotels = [
        {
            "hotel_id": "SH-H100",
            "name": "上海静安商务酒店",
            "location": location,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "price_per_night": 420,
            "rating": 4.5,
        },
        {
            "hotel_id": "SH-H203",
            "name": "陆家嘴轻奢酒店",
            "location": location,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "price_per_night": 560,
            "rating": 4.7,
        },
        {
            "hotel_id": "SH-H330",
            "name": "虹桥城市快捷酒店",
            "location": location,
            "checkin": checkin,
            "checkout": checkout,
            "guests": guests,
            "price_per_night": 300,
            "rating": 4.2,
        },
    ]
    return hotels


@tool
def get_weather(city: str, date: str) -> Dict[str, Any]:
    """获取天气概况（Mock）。"""
    return {
        "city": city,
        "date": date,
        "condition": "多云",
        "temperature_c": "19-27",
        "advice": "适合出行，建议携带薄外套。",
    }


@tool
def calculator(expression: str) -> str:
    """数学计算（Mock，受限表达式）。"""
    allowed = re.fullmatch(r"[0-9\s\+\-\*\/\(\)\.]+", expression)
    if not allowed:
        return "Error: expression contains invalid characters"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


@tool
def booking_flight(flight_id: str, passenger_info: Dict[str, Any]) -> Dict[str, Any]:
    """下订单（Mock，30% 概率失败）。"""
    if random.random() < 0.3:
        raise RuntimeError("Mock booking failure: payment gateway timeout")
    return {
        "status": "confirmed",
        "booking_id": f"BK-{flight_id}-{int(time.time())}",
        "flight_id": flight_id,
        "passenger_info": passenger_info,
    }


TOOLS = [search_flights, search_hotels, get_weather, calculator, booking_flight]
TOOL_MAP = {t.name: t for t in TOOLS}


# -------------------- 第四部分：EvaluationTracer --------------------
@dataclass
class ToolCallRecord:
    tool_name: str
    args: Dict[str, Any]
    result: Any
    success: bool
    is_redundant: bool
    timestamp: float


@dataclass
class EvaluationTracer:
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_steps: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    errors: int = 0
    recoveries: int = 0

    _call_fingerprint_set: set[str] = field(default_factory=set)

    def record_tool_call(self, tool_name: str, args: Dict[str, Any], result: Any, success: bool) -> None:
        fingerprint = f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
        is_redundant = fingerprint in self._call_fingerprint_set
        self._call_fingerprint_set.add(fingerprint)
        self.tool_calls.append(
            ToolCallRecord(
                tool_name=tool_name,
                args=args,
                result=result,
                success=success,
                is_redundant=is_redundant,
                timestamp=time.time(),
            )
        )

    def record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += max(prompt_tokens, 0)
        self.completion_tokens += max(completion_tokens, 0)

    def record_step(self) -> None:
        self.total_steps += 1

    def record_error(self) -> None:
        self.errors += 1

    def record_recovery(self) -> None:
        self.recoveries += 1

    def finish(self) -> None:
        self.end_time = time.time()


# -------------------- 第三部分：LangGraph Agent --------------------
class AgentState(TypedDict):
    messages: List[BaseMessage]
    tool_calls_log: List[Dict[str, Any]]
    token_usage: Dict[str, int]
    error_count: int


def extract_usage(ai_message: AIMessage) -> Tuple[int, int]:
    usage = ai_message.response_metadata.get("token_usage", {}) if ai_message.response_metadata else {}
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    return prompt_tokens, completion_tokens


def create_llm(model_name: str, temperature: float = 0) -> Optional[ChatOpenAI]:
    api_key = CONFIG["OPENAI_API_KEY"]
    if not api_key:
        logger.error("Missing OPENAI_API_KEY, LLM call will use fallback flow.")
        return None
    try:
        return ChatOpenAI(model=model_name, temperature=temperature, api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize ChatOpenAI: %s", exc)
        return None


def build_agent_graph(tracer: EvaluationTracer) -> Any:
    llm_client = create_llm(CONFIG["MODEL_NAME"], temperature=0.2)
    llm = llm_client.bind_tools(TOOLS) if llm_client is not None else None

    def agent_node(state: AgentState) -> AgentState:
        tracer.record_step()
        messages = state["messages"]
        try:
            if llm is None:
                raise RuntimeError("Agent LLM not available")
            response = llm.invoke(messages)
            prompt_tk, completion_tk = extract_usage(response)
            tracer.record_tokens(prompt_tk, completion_tk)
            state["token_usage"]["prompt_tokens"] += prompt_tk
            state["token_usage"]["completion_tokens"] += completion_tk
            state["messages"].append(response)
        except Exception as exc:  # noqa: BLE001
            tracer.record_error()
            state["error_count"] += 1
            logger.error("Agent node failed: %s", exc)
            state["messages"].append(
                AIMessage(content="抱歉，我在规划过程中遇到异常，先给你一个保守行程建议并继续尝试。")
            )
        return state

    def tool_node(state: AgentState) -> AgentState:
        tracer.record_step()
        last_msg = state["messages"][-1]
        if not isinstance(last_msg, AIMessage):
            return state

        for call in last_msg.tool_calls or []:
            tool_name = call.get("name", "")
            args = call.get("args", {}) or {}
            tool_call_id = call.get("id", f"toolcall-{int(time.time() * 1000)}")
            selected_tool = TOOL_MAP.get(tool_name)
            if selected_tool is None:
                tracer.record_error()
                state["error_count"] += 1
                error_text = f"Unknown tool: {tool_name}"
                state["messages"].append(ToolMessage(content=error_text, tool_call_id=tool_call_id))
                tracer.record_tool_call(tool_name, args, error_text, False)
                continue

            try:
                result = selected_tool.invoke(args)
                tracer.record_tool_call(tool_name, args, result, True)
                state["tool_calls_log"].append(
                    {"tool_name": tool_name, "args": args, "result": result, "success": True}
                )
                state["messages"].append(
                    ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)
                )
            except Exception as exc:  # noqa: BLE001
                tracer.record_error()
                state["error_count"] += 1
                error_msg = f"Tool error: {exc}"
                tracer.record_tool_call(tool_name, args, error_msg, False)
                state["tool_calls_log"].append(
                    {"tool_name": tool_name, "args": args, "result": error_msg, "success": False}
                )
                state["messages"].append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))

        if state["error_count"] > 0:
            tracer.record_recovery()
        return state

    def should_continue(state: AgentState) -> Literal["tool", "end"]:
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "tool"
        return "end"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tool": "tool", "end": END})
    graph.add_edge("tool", "agent")
    return graph.compile()


# -------------------- 第五部分：确定性评估函数 --------------------
def log_eval_metric(metric_name: str, input_desc: Any, output: Any, basis: str, conclusion: str) -> None:
    logger.info("[EVAL] ============================================================")
    logger.info("[EVAL] 当前评估指标: %s", metric_name)
    logger.info("[EVAL] 评估指标输入: %s", json.dumps(input_desc, ensure_ascii=False))
    logger.info("[EVAL] 评估指标输出: %s", json.dumps(output, ensure_ascii=False))
    logger.info("[EVAL] 评估依据: %s", basis)
    logger.info("[EVAL] 评估结果: %s", conclusion)
    logger.info("[EVAL] ============================================================")


def eval_tool_call_accuracy(tracer: EvaluationTracer) -> float:
    if not tracer.tool_calls:
        score = 0.0
    else:
        score = sum(1 for c in tracer.tool_calls if c.success) / len(tracer.tool_calls)
    log_eval_metric(
        "工具调用准确率",
        {"tool_calls": len(tracer.tool_calls)},
        {"accuracy": round(score, 4)},
        "正确调用次数 / 总调用次数",
        "通过" if score >= 0.8 else "需优化",
    )
    return score


def eval_redundancy_rate(tracer: EvaluationTracer) -> float:
    if not tracer.tool_calls:
        rate = 0.0
    else:
        rate = sum(1 for c in tracer.tool_calls if c.is_redundant) / len(tracer.tool_calls)
    log_eval_metric(
        "冗余步骤率",
        {"tool_calls": len(tracer.tool_calls)},
        {"redundancy_rate": round(rate, 4)},
        "冗余步骤数 / 总步骤数（用重复工具参数调用近似）",
        "通过" if rate <= 0.2 else "需优化",
    )
    return rate


def eval_avg_steps(tracer: EvaluationTracer) -> float:
    avg_steps = float(tracer.total_steps)
    log_eval_metric(
        "平均步骤数",
        {"total_steps": tracer.total_steps, "task_count": 1},
        {"avg_steps": avg_steps},
        "总步骤 / 任务数",
        "通过" if avg_steps <= CONFIG["MAX_STEPS"] else "步骤偏多",
    )
    return avg_steps


def eval_token_consumption(tracer: EvaluationTracer) -> Dict[str, int]:
    token_data = {
        "prompt_tokens": tracer.prompt_tokens,
        "completion_tokens": tracer.completion_tokens,
        "total_tokens": tracer.prompt_tokens + tracer.completion_tokens,
    }
    log_eval_metric("Token 消耗", {"token_usage": token_data}, token_data, "prompt + completion", "已统计")
    return token_data


def eval_latency(tracer: EvaluationTracer) -> float:
    end_time = tracer.end_time if tracer.end_time is not None else time.time()
    latency = max(end_time - tracer.start_time, 0.0)
    log_eval_metric(
        "任务耗时",
        {"start_time": tracer.start_time, "end_time": end_time},
        {"latency_seconds": round(latency, 4)},
        "从输入到输出总耗时",
        "通过" if latency < 30 else "耗时偏高",
    )
    return latency


def eval_cost_efficiency(tracer: EvaluationTracer, task_value: float = 1.0) -> Dict[str, float]:
    prompt_cost = tracer.prompt_tokens / 1000 * CONFIG["PRICE_PROMPT_PER_1K"]
    completion_cost = tracer.completion_tokens / 1000 * CONFIG["PRICE_COMPLETION_PER_1K"]
    total_cost = prompt_cost + completion_cost
    efficiency = task_value / total_cost if total_cost > 0 else 0.0
    result = {
        "prompt_cost": round(prompt_cost, 6),
        "completion_cost": round(completion_cost, 6),
        "total_cost": round(total_cost, 6),
        "cost_efficiency": round(efficiency, 4),
    }
    log_eval_metric(
        "成本效率",
        {"task_value": task_value, "price_config": {"prompt": CONFIG["PRICE_PROMPT_PER_1K"], "completion": CONFIG["PRICE_COMPLETION_PER_1K"]}},
        result,
        "任务价值 / API 成本",
        "通过" if efficiency >= 5 else "可优化",
    )
    return result


def eval_tool_call_count(tracer: EvaluationTracer) -> int:
    count = len(tracer.tool_calls)
    log_eval_metric("工具调用次数", {"tool_calls": count}, {"count": count}, "统计全部工具调用次数", "已统计")
    return count


def eval_booking_invoked(tracer: EvaluationTracer) -> bool:
    invoked = any(c.tool_name == "booking_flight" for c in tracer.tool_calls)
    log_eval_metric(
        "是否调用 booking_flight",
        {"tool_calls": [c.tool_name for c in tracer.tool_calls]},
        {"booking_flight_called": invoked},
        "检查调用日志是否包含 booking_flight",
        "已调用" if invoked else "未调用",
    )
    return invoked


# -------------------- 第六部分：LLM 评估函数 --------------------
def safe_json_parse(raw_text: str) -> Dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    return json.loads(stripped)


def call_judge_once(metric_name: str, system_prompt: str, user_prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    input_desc = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "judge_model": CONFIG["JUDGE_MODEL"],
    }
    try:
        judge = create_llm(CONFIG["JUDGE_MODEL"], temperature=0)
        if judge is None:
            raise RuntimeError("Judge LLM not available")
        resp = judge.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        data = safe_json_parse(resp.content if isinstance(resp.content, str) else json.dumps(resp.content, ensure_ascii=False))
        if "score" not in data:
            data["score"] = fallback.get("score", 0.0)
        if "reasoning" not in data:
            data["reasoning"] = fallback.get("reasoning", "judge missing reasoning")
        log_eval_metric(metric_name, input_desc, data, "LLM-as-Judge 单次独立评估并解析 JSON", "完成")
        return data
    except Exception as exc:  # noqa: BLE001
        logger.error("Judge evaluation failed (%s): %s", metric_name, exc)
        degraded = {**fallback, "reasoning": f"fallback due to error: {exc}"}
        log_eval_metric(metric_name, input_desc, degraded, "LLM 调用异常时使用降级结果", "降级完成")
        return degraded


def eval_task_success_rate(conversation: str, final_answer: str, user_goal: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请判断最终结果是否达成用户目标，0或1。\n"
        f"用户目标: {user_goal}\n对话: {conversation}\n最终回复: {final_answer}\n"
        "输出格式: {\"score\": 0或1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("任务成功率 (SR)", system_prompt, user_prompt, {"score": 0, "reasoning": "fallback", "details": []})


def eval_partial_completion_rate(conversation: str, final_answer: str, subtasks: List[str]) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估每个子目标是否完成，并给出完成率(0-1)。\n"
        f"子目标: {subtasks}\n对话: {conversation}\n最终回复: {final_answer}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": [{\"subtask\":\"...\",\"done\":true}]}"
    )
    return call_judge_once("部分完成率 (PCR)", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_quality_score(conversation: str, final_answer: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请从1-5分评估结果质量。\n"
        f"对话: {conversation}\n最终回复: {final_answer}\n"
        "输出格式: {\"score\": 1-5, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("结果质量分 (QS)", system_prompt, user_prompt, {"score": 1, "reasoning": "fallback", "details": []})


def eval_goal_coverage_rate(conversation: str, final_answer: str, goals: List[str]) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估目标覆盖率（0-1）并逐个目标判断。\n"
        f"目标列表: {goals}\n对话: {conversation}\n最终回复: {final_answer}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": [{\"goal\":\"...\",\"covered\":true}]}"
    )
    return call_judge_once("目标覆盖率 (GCR)", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_hallucination_rate(conversation: str, tool_results: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估幻觉率（0-1，越低越好）。\n"
        f"对话: {conversation}\n工具结果: {tool_results}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("幻觉率", system_prompt, user_prompt, {"score": 1.0, "reasoning": "fallback", "details": []})


def eval_plan_reasonableness(tool_call_sequence: List[str], conversation: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估规划路径合理性（0-1，越高越好）。\n"
        f"工具调用顺序: {tool_call_sequence}\n对话: {conversation}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("计划合理性", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_error_recovery(tracer: EvaluationTracer, conversation: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估错误恢复率（0-1）。\n"
        f"错误数: {tracer.errors}, 恢复事件数: {tracer.recoveries}\n对话: {conversation}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("错误恢复率", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_adversarial_robustness(conversation: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估面对误导性信息时的对抗鲁棒性（0-1）。\n"
        f"对话: {conversation}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("对抗鲁棒性", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_consistency(results_list: List[str]) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估同一问题多次运行结果一致性（0-1）。\n"
        f"多次运行结果: {results_list}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("一致性", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


def eval_boundary_handling(tracer: EvaluationTracer, conversation: str) -> Dict[str, Any]:
    system_prompt = "你是一个专业的AI Agent评估专家。只输出JSON。"
    user_prompt = (
        "请评估异常输入和边界条件处理能力（0-1）。\n"
        f"错误数: {tracer.errors}\n对话: {conversation}\n"
        "输出格式: {\"score\": 0-1, \"reasoning\": \"...\", \"details\": []}"
    )
    return call_judge_once("边界处理", system_prompt, user_prompt, {"score": 0.0, "reasoning": "fallback", "details": []})


# -------------------- 第七部分：EvaluationReport --------------------
@dataclass
class EvalMetricResult:
    name: str
    score: float
    detail: Dict[str, Any]


@dataclass
class EvaluationReport:
    task_completion: List[EvalMetricResult] = field(default_factory=list)
    process_quality: List[EvalMetricResult] = field(default_factory=list)
    efficiency: List[EvalMetricResult] = field(default_factory=list)
    robustness: List[EvalMetricResult] = field(default_factory=list)

    def _avg(self, items: List[EvalMetricResult]) -> float:
        if not items:
            return 0.0
        return sum(item.score for item in items) / len(items)

    def total_score(self) -> float:
        all_items = self.task_completion + self.process_quality + self.efficiency + self.robustness
        if not all_items:
            return 0.0
        return sum(i.score for i in all_items) / len(all_items)

    def suggestions(self) -> List[str]:
        recs: List[str] = []
        if self._avg(self.process_quality) < 0.75:
            recs.append("优化工具调用顺序，减少冗余调用与幻觉风险。")
        if self._avg(self.efficiency) < 0.7:
            recs.append("控制步骤数与Token消耗，提高成本效率。")
        if self._avg(self.robustness) < 0.7:
            recs.append("增加故障重试与边界输入处理策略。")
        if not recs:
            recs.append("整体表现良好，可继续增强用户偏好建模能力。")
        return recs

    def print_report(self) -> None:
        logger.info("\n================= Evaluation Report =================")
        logger.info("任务完成小计: %.4f", self._avg(self.task_completion))
        logger.info("过程质量小计: %.4f", self._avg(self.process_quality))
        logger.info("效率指标小计: %.4f", self._avg(self.efficiency))
        logger.info("鲁棒性小计: %.4f", self._avg(self.robustness))
        logger.info("整体评分: %.4f", self.total_score())
        logger.info("建议: %s", " | ".join(self.suggestions()))
        logger.info("====================================================\n")


# -------------------- 第八部分：main() --------------------
def normalize_score(metric_name: str, raw_score: float) -> float:
    if metric_name == "结果质量分 (QS)":
        return min(max(raw_score / 5.0, 0.0), 1.0)
    if metric_name in {"幻觉率", "冗余步骤率"}:
        return 1.0 - min(max(raw_score, 0.0), 1.0)
    return min(max(raw_score, 0.0), 1.0)


def extract_final_answer(messages: List[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            return str(msg.content)
    return ""


def run_scenario() -> Tuple[AgentState, EvaluationTracer]:
    tracer = EvaluationTracer()
    app = build_agent_graph(tracer)

    start_date = datetime.now().date() + timedelta(days=7)
    checkin = str(start_date)
    checkout = str(start_date + timedelta(days=2))

    state: AgentState = {
        "messages": [],
        "tool_calls_log": [],
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "error_count": 0,
    }

    user_turns = [
        (
            "我想从北京去上海，3天2晚，2位成人，总预算3000元，请帮我做综合规划，"
            "要包含航班、酒店、天气、预算测算。"
        ),
        "优先选择性价比路线，并尝试帮我下单最便宜且时间合适的航班。",
        "最后请输出一个清晰的行程与预算摘要。",
    ]

    for utterance in user_turns:
        state["messages"].append(HumanMessage(content=utterance))
        state = app.invoke(state, config={"recursion_limit": 30})

    tracer.finish()
    return state, tracer


def main() -> None:
    logger.info("开始运行智能旅行规划助手 Agent + 评估系统")
    final_state, tracer = run_scenario()

    conversation_text = "\n".join(
        [f"{m.__class__.__name__}: {getattr(m, 'content', '')}" for m in final_state["messages"]]
    )
    final_answer = extract_final_answer(final_state["messages"])
    tool_results = json.dumps(final_state["tool_calls_log"], ensure_ascii=False)
    tool_sequence = [entry["tool_name"] for entry in final_state["tool_calls_log"]]

    # 任务完成类（4 个指标，4 次 LLM）
    sr = eval_task_success_rate(
        conversation_text,
        final_answer,
        "北京到上海3天2晚、预算内、覆盖航班酒店天气预算并给出可执行建议",
    )
    pcr = eval_partial_completion_rate(
        conversation_text,
        final_answer,
        ["航班方案", "酒店方案", "天气说明", "预算测算", "最终摘要"],
    )
    qs = eval_quality_score(conversation_text, final_answer)
    gcr = eval_goal_coverage_rate(
        conversation_text,
        final_answer,
        ["预算内", "含航班", "含酒店", "含天气", "可执行计划"],
    )

    # 过程质量类（2 LLM + 2 确定性）
    tool_acc = eval_tool_call_accuracy(tracer)
    halluc = eval_hallucination_rate(conversation_text, tool_results)
    plan = eval_plan_reasonableness(tool_sequence, conversation_text)
    redundancy = eval_redundancy_rate(tracer)

    # 效率类（确定性）
    avg_steps = eval_avg_steps(tracer)
    token_stats = eval_token_consumption(tracer)
    latency = eval_latency(tracer)
    cost_eff = eval_cost_efficiency(tracer, task_value=max(float(sr.get("score", 0)), 0.1))

    # 额外确定性观测（用户要求强调）
    eval_tool_call_count(tracer)
    eval_booking_invoked(tracer)

    # 鲁棒性类（4 个指标，4 次 LLM）
    err_rec = eval_error_recovery(tracer, conversation_text)
    adv = eval_adversarial_robustness(conversation_text)
    consistency = eval_consistency([final_answer, final_answer])
    boundary = eval_boundary_handling(tracer, conversation_text)

    report = EvaluationReport(
        task_completion=[
            EvalMetricResult("任务成功率 (SR)", normalize_score("任务成功率 (SR)", float(sr.get("score", 0))), sr),
            EvalMetricResult("部分完成率 (PCR)", normalize_score("部分完成率 (PCR)", float(pcr.get("score", 0))), pcr),
            EvalMetricResult("结果质量分 (QS)", normalize_score("结果质量分 (QS)", float(qs.get("score", 1))), qs),
            EvalMetricResult("目标覆盖率 (GCR)", normalize_score("目标覆盖率 (GCR)", float(gcr.get("score", 0))), gcr),
        ],
        process_quality=[
            EvalMetricResult("工具调用准确率", normalize_score("工具调用准确率", tool_acc), {"score": tool_acc}),
            EvalMetricResult("幻觉率", normalize_score("幻觉率", float(halluc.get("score", 1))), halluc),
            EvalMetricResult("计划合理性", normalize_score("计划合理性", float(plan.get("score", 0))), plan),
            EvalMetricResult("冗余步骤率", normalize_score("冗余步骤率", redundancy), {"score": redundancy}),
        ],
        efficiency=[
            EvalMetricResult("平均步骤数", max(0.0, 1.0 - avg_steps / max(CONFIG["MAX_STEPS"], 1)), {"score": avg_steps}),
            EvalMetricResult(
                "Token 消耗",
                max(0.0, 1.0 - token_stats["total_tokens"] / 10000),
                {"score": token_stats["total_tokens"], **token_stats},
            ),
            EvalMetricResult("任务耗时", max(0.0, 1.0 - latency / 60), {"score": latency}),
            EvalMetricResult("成本效率", min(cost_eff["cost_efficiency"] / 10, 1.0), cost_eff),
        ],
        robustness=[
            EvalMetricResult("错误恢复率", normalize_score("错误恢复率", float(err_rec.get("score", 0))), err_rec),
            EvalMetricResult("对抗鲁棒性", normalize_score("对抗鲁棒性", float(adv.get("score", 0))), adv),
            EvalMetricResult("一致性", normalize_score("一致性", float(consistency.get("score", 0))), consistency),
            EvalMetricResult("边界处理", normalize_score("边界处理", float(boundary.get("score", 0))), boundary),
        ],
    )

    report.print_report()


if __name__ == "__main__":
    main()
