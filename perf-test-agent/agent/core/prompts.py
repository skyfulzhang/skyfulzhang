"""
agent/core/prompts.py
LangChain Prompt 模板集合 - 性能测试智能体的所有提示词。
"""

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

# ── 系统提示词 ────────────────────────────────────────────────────────────────

PERFORMANCE_TEST_AGENT_SYSTEM_PROMPT = """你是一个专业的性能测试工程师智能体，专注于使用 Grafana k6 进行 API 性能测试。
你的职责包括：
1. 根据用户需求生成高质量的 k6 测试脚本
2. 通过 GitHub API 管理测试脚本和 CI 工作流
3. 分析测试结果，识别性能瓶颈
4. 提供具体可行的性能优化建议
5. 跟踪性能趋势，发现退化问题

在生成测试脚本时，你应该：
- 设置合理的 thresholds（p95 < 500ms, 错误率 < 1%）
- 包含适当的 sleep 防止过度压测
- 添加详细注释说明测试意图
- 根据测试类型选择合适的 executor

工具使用原则：
- 优先使用已有的脚本模板
- 触发 workflow 后必须等待完成再分析
- 报告分析要聚焦在关键业务指标

当前时间：{current_time}
"""

# ── k6 脚本生成 Prompt ────────────────────────────────────────────────────────

K6_SCRIPT_GENERATION_PROMPT = PromptTemplate(
    input_variables=[
        "target_url",
        "test_type",
        "vus",
        "duration",
        "ramp_up_time",
        "description",
        "expected_p95_ms",
        "expected_error_rate",
        "custom_endpoints",
        "auth_headers",
    ],
    template="""请为以下 API 生成一个高质量的 k6 性能测试脚本。

## 测试目标
- 目标 URL: {target_url}
- 测试类型: {test_type}
- 测试描述: {description}

## 负载配置
- 并发用户数 (VUs): {vus}
- 稳定期时长: {duration}
- 爬升时间: {ramp_up_time}

## 性能预期
- p95 响应时间目标: < {expected_p95_ms}ms
- 错误率目标: < {expected_error_rate}%

## 接口信息
{custom_endpoints}

## 认证信息
{auth_headers}

## 要求
1. 使用标准 k6 ES6 模块语法
2. 包含自定义指标（Rate, Trend, Counter）
3. 设置合理的 thresholds
4. 使用 group() 组织测试逻辑
5. 实现 handleSummary() 生成本地报告
6. 所有关键配置通过 __ENV 环境变量注入
7. 添加中文注释说明测试意图

请直接输出完整的 JavaScript 代码，不需要任何额外说明。
""",
)

# ── 报告分析 Prompt ───────────────────────────────────────────────────────────

REPORT_ANALYSIS_PROMPT = PromptTemplate(
    input_variables=[
        "report_json",
        "baseline_data",
        "test_name",
        "target_url",
    ],
    template="""请分析以下 k6 性能测试报告，识别性能瓶颈并提供优化建议。

## 测试信息
- 测试名称: {test_name}
- 目标 URL: {target_url}

## 当前测试报告
```json
{report_json}
```

## 历史基线数据（如有）
```json
{baseline_data}
```

## 分析维度
1. **响应时间分析**: 评估 avg/p90/p95/p99/max，识别长尾延迟问题
2. **错误率分析**: 分析失败原因，是否超过阈值
3. **吞吐量分析**: RPS 是否满足业务需求
4. **资源利用**: 数据传输量是否合理
5. **阈值达成**: 哪些阈值通过/失败
6. **趋势对比**: 与基线相比性能是否退化

## 输出格式要求
请严格按照以下 JSON 格式输出分析结果：
```json
{{
  "overall_assessment": "PASS|WARN|FAIL",
  "performance_score": 0-100,
  "key_findings": ["发现1", "发现2"],
  "bottlenecks": [
    {{
      "type": "latency|throughput|error|resource",
      "severity": "high|medium|low",
      "description": "问题描述",
      "metric_value": "具体指标值"
    }}
  ],
  "recommendations": [
    {{
      "priority": "HIGH|MEDIUM|LOW",
      "category": "threshold|script|infrastructure|code",
      "title": "建议标题",
      "description": "详细描述",
      "script_change": "// 相关代码修改示例"
    }}
  ]
}}
```
""",
)

# ── 优化建议 Prompt ───────────────────────────────────────────────────────────

OPTIMIZATION_SUGGESTION_PROMPT = PromptTemplate(
    input_variables=[
        "current_script",
        "analysis_result",
        "optimization_goals",
    ],
    template="""基于以下性能测试结果和分析，请提供具体的 k6 脚本优化方案。

## 当前脚本
```javascript
{current_script}
```

## 性能分析结果
```json
{analysis_result}
```

## 优化目标
{optimization_goals}

## 要求
1. 针对每个识别的性能问题提供具体的脚本修改方案
2. 解释每个修改的理由
3. 提供完整的优化后脚本

## 输出格式
```json
{{
  "changes": [
    {{
      "location": "修改位置描述",
      "original": "原始代码片段",
      "optimized": "优化后代码片段",
      "reason": "修改理由"
    }}
  ],
  "optimized_script": "// 完整的优化后脚本内容"
}}
```
""",
)

# ── 交互式对话 Prompt ─────────────────────────────────────────────────────────

INTERACTIVE_CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            PERFORMANCE_TEST_AGENT_SYSTEM_PROMPT,
        ),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

# ── ReAct Agent Prompt ────────────────────────────────────────────────────────

REACT_AGENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            PERFORMANCE_TEST_AGENT_SYSTEM_PROMPT
            + """

你可以使用以下工具来完成任务：
{tools}

工具名称列表: {tool_names}

使用以下格式：
Thought: 思考当前需要做什么
Action: 选择要使用的工具名称
Action Input: 工具输入参数（JSON 格式）
Observation: 工具执行结果
... (重复 Thought/Action/Observation)
Thought: 我已经完成了所有必要操作
Final Answer: 最终答案
""",
        ),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)
