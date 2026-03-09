# perf-test-agent 项目架构

## 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户输入（CLI / 交互模式）                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  LangChain ReAct Agent                          │
│   （PerformanceTestAgent）                                       │
│   - 理解用户意图                                                  │
│   - 选择工具                                                     │
│   - 整合结果                                                     │
└──────────────┬──────────────────────┬───────────────────────────┘
               │                      │
       ┌───────┴───────┐      ┌───────┴────────┐
       ▼               ▼      ▼                ▼
  ┌─────────┐    ┌──────────┐  ┌─────────┐  ┌──────────┐
  │k6 Script│    │ Report   │  │ GitHub  │  │Workflow  │
  │ Tools   │    │ Analyzer │  │  Tools  │  │  Tools   │
  └────┬────┘    └────┬─────┘  └────┬────┘  └────┬─────┘
       │              │             │              │
       ▼              ▼             ▼              ▼
  ┌─────────┐    ┌──────────┐  ┌─────────┐  ┌──────────┐
  │K6Script │    │ Report   │  │ GitHub  │  │ GitHub   │
  │ Service │    │ Service  │  │ Service │  │ Service  │
  └────┬────┘    └────┬─────┘  └────┬────┘  └────┬─────┘
       │              │             │              │
       ▼              ▼             └──────┬───────┘
  ┌─────────┐    ┌──────────┐             ▼
  │k6 Script│    │ HTML/JSON│      ┌─────────────┐
  │Templates│    │ Reports  │      │  PyGitHub   │
  └─────────┘    └──────────┘      │  REST API   │
                                   └──────┬──────┘
                                          │
                                          ▼
                                   ┌─────────────┐
                                   │  GitHub     │
                                   │  Actions    │
                                   │ (k6-action) │
                                   └─────────────┘
```

## Agent 执行流程

```
用户输入（URL + 测试要求）
    │
    ▼
[Step 1] generate_k6_script
    │  使用模板或 LLM 生成 k6 JS 脚本
    ▼
[Step 2] validate_k6_script
    │  静态语法检查
    ▼
[Step 3] upload_k6_script
    │  PyGitHub 上传脚本到分支
    ▼
[Step 4] trigger_performance_test / trigger_k6_workflow
    │  触发 workflow_dispatch 事件
    ▼
[Step 5] wait_for_workflow_completion / monitor_workflow_progress
    │  轮询等待（最长 30 分钟）
    ▼
[Step 6] get_latest_report
    │  从仓库获取 JSON 报告
    ▼
[Step 7] analyze_performance_report
    │  解析指标 + LLM 分析
    ▼
[Step 8] optimize_script_thresholds（可选）
    │  根据实测数据优化阈值
    ▼
[Step 9] create_pr_with_optimized_script（如有改进）
    │  创建优化 PR
    ▼
返回完整测试报告 + 优化建议
```

## 目录结构说明

```
perf-test-agent/
├── agent/                  # Python 包主目录
│   ├── core/               # Agent 核心（LLM、Prompts、AgentExecutor）
│   ├── tools/              # LangChain Tools 封装
│   ├── services/           # 底层服务（GitHub、k6、Report）
│   ├── models/             # Pydantic 数据模型
│   └── utils/              # 工具（配置、日志、重试）
├── k6_scripts/
│   ├── templates/          # k6 脚本模板（5 种测试类型）
│   └── utils/              # k6 公共辅助函数
├── .github/
│   ├── workflows/          # GitHub Actions Workflows
│   └── scripts/            # Actions 辅助脚本（Python）
├── tests/
│   ├── unit/               # 单元测试（无外部依赖）
│   └── integration/        # 集成测试（需真实 API）
└── docs/                   # 项目文档
```

## 关键技术选型

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| LLM 框架 | LangChain 0.3 | ReAct Agent + StructuredTool |
| LLM 提供商 | OpenAI / Azure / Ollama | 可配置切换 |
| GitHub 操作 | PyGitHub 2.x | 上传脚本、触发 Workflow |
| 性能测试 | Grafana k6 | via `grafana/k6-action` |
| 配置管理 | pydantic-settings | .env 文件支持 |
| 日志 | structlog | JSON / text 双格式 |
| 重试 | tenacity | 指数退避 |
| CLI | typer + rich | 美观的命令行界面 |
| 报告模板 | Jinja2 + Chart.js | HTML 可视化报告 |

## 错误处理策略

```
GitHub API 错误
  ├── RateLimitExceededException → 等待 60s 后重试（最多 5 次）
  ├── 404 Not Found → 上报错误，不重试
  ├── 50x Server Error → 指数退避重试（1s → 2s → 4s → 8s）
  └── 网络错误 → 随机指数退避重试

Workflow 错误
  ├── 超时 → 记录当前状态，抛出 TimeoutError
  ├── 触发失败 → 抛出 RuntimeError
  └── 完成但失败 → 返回 WorkflowRun（conclusion='failure'）

报告解析错误
  ├── JSON 格式错误 → 抛出 ValueError
  └── 指标缺失 → 使用默认值 0.0，不抛出异常
```
