# ⚡ perf-test-agent

**企业级性能测试智能体** - 将 LangChain LLM、PyGitHub、Grafana k6 和 GitHub Actions CI 有机结合，实现智能化的 API 性能测试全流程自动化。

## 🏗️ 系统架构

```
                    ┌─────────────────────┐
                    │    用户 (CLI/交互)    │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  LangChain ReAct    │
                    │     Agent (LLM)     │
                    │   OpenAI/Azure/     │
                    │      Ollama         │
                    └──┬──────┬──────┬───┘
                       │      │      │
             ┌─────────┘      │      └──────────┐
             │                │                 │
    ┌────────▼───────┐  ┌─────▼──────┐  ┌──────▼──────┐
    │  k6 Script     │  │  Report    │  │  GitHub     │
    │  Tools         │  │  Analyzer  │  │  Tools      │
    │  (生成/验证)    │  │  (解析/分析)│  │  (上传/触发)│
    └────────┬───────┘  └─────┬──────┘  └──────┬──────┘
             │                │                 │
    ┌────────▼───────┐  ┌─────▼──────┐  ┌──────▼──────┐
    │  k6 Templates  │  │ HTML/JSON  │  │  PyGitHub   │
    │  (5 种测试类型) │  │  Reports   │  │ + Actions   │
    └────────────────┘  └────────────┘  └──────┬──────┘
                                               │
                                        ┌──────▼──────┐
                                        │ grafana/    │
                                        │ k6-action   │
                                        │  (执行测试)  │
                                        └─────────────┘
```

## ✨ 核心功能

| 功能 | 描述 |
|------|------|
| 🤖 **智能脚本生成** | LLM 根据需求自动生成 k6 测试脚本 |
| 🚀 **一键触发测试** | PyGitHub API 上传脚本 + 触发 Actions |
| 📊 **自动分析报告** | 解析 JSON 报告 + LLM 识别性能瓶颈 |
| 💡 **优化建议** | 自动生成优化方案并创建 PR |
| 📅 **定时回归** | 每日自动性能回归测试 + 失败告警 |
| 💬 **交互对话** | 自然语言驱动的持续对话模式 |

## 🚀 快速开始

### 环境要求

- Python 3.11+
- OpenAI API Key（或 Azure OpenAI / Ollama）
- GitHub Personal Access Token（`repo` + `workflow` 权限）

### 安装

```bash
# 克隆仓库
git clone https://github.com/skyfulzhang/skyfulzhang
cd skyfulzhang/perf-test-agent

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
vim .env  # 填入真实配置
```

### 运行性能测试

```bash
# 执行完整测试流水线
python -m agent.main run-test https://httpbin.org --type load

# 压力测试
python -m agent.main run-test https://api.example.com --type stress --req "模拟双11大促"

# 交互式智能对话
python -m agent.main interactive

# 使用 Makefile
make run-test URL=https://httpbin.org
make interactive
```

## 📁 项目结构

```
perf-test-agent/
├── agent/
│   ├── core/
│   │   ├── agent.py          # LangChain ReAct Agent 核心
│   │   ├── llm_factory.py    # LLM 工厂（OpenAI/Azure/Ollama）
│   │   └── prompts.py        # Prompt 模板
│   ├── tools/
│   │   ├── github_tools.py   # GitHub 操作 LangChain Tools
│   │   ├── k6_script_tools.py # k6 脚本工具
│   │   ├── report_analyzer.py # 报告分析工具
│   │   └── workflow_tools.py  # Workflow 工具
│   ├── services/
│   │   ├── github_service.py  # PyGitHub 底层服务
│   │   ├── k6_service.py      # k6 脚本模板服务
│   │   └── report_service.py  # 报告解析服务
│   ├── models/
│   │   ├── test_config.py     # Pydantic 数据模型
│   │   └── report_models.py   # 报告模型
│   ├── utils/
│   │   ├── config.py          # pydantic-settings 配置管理
│   │   ├── logger.py          # structlog 结构化日志
│   │   └── retry.py           # 指数退避重试装饰器
│   └── main.py                # CLI 入口（typer）
├── k6_scripts/
│   ├── templates/             # 5 种测试类型模板
│   │   ├── http_load_test.js  # 负载测试
│   │   ├── stress_test.js     # 压力测试
│   │   ├── spike_test.js      # 尖峰测试
│   │   ├── soak_test.js       # 浸泡测试
│   │   └── api_test.js        # API 端到端测试
│   └── utils/helpers.js       # 公共辅助函数
├── .github/
│   ├── workflows/
│   │   ├── k6-performance-test.yml    # 主测试 Workflow
│   │   └── k6-schedule-test.yml       # 定时回归 Workflow
│   └── scripts/
│       ├── generate_html_report.py    # HTML 报告生成
│       ├── check_thresholds.py        # 阈值门禁检查
│       └── post_summary.py            # Actions Job Summary
├── tests/
│   ├── unit/                  # 单元测试（无外部依赖）
│   └── integration/           # 集成测试
├── docs/
│   ├── architecture.md        # 架构文档
│   └── usage.md               # 使用指南
├── requirements.txt
├── pyproject.toml
├── Makefile
└── .env.example
```

## ⚙️ 配置说明

复制 `.env.example` 并修改：

```env
# GitHub 配置（必填）
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO_OWNER=your_org
GITHUB_REPO_NAME=your_repo

# LLM 配置（三选一）
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your_key
OPENAI_MODEL=gpt-4o

# 日志
LOG_LEVEL=INFO
LOG_FORMAT=json   # json（生产）或 text（开发）
```

## 📊 测试类型

| 类型 | 适用场景 | 关键指标 |
|------|----------|----------|
| **load** | 日常回归，验证正常负载性能 | P95 < 500ms |
| **stress** | 超负荷测试，找系统断点 | 找到崩溃点 VUs |
| **spike** | 突发流量（大促、新闻热点） | 错误率 < 15% |
| **soak** | 长时间稳定性（内存泄漏检测） | P95 不随时间退化 |
| **api** | API 功能正确性 + 性能综合 | 功能错误率 < 1% |

## 🛠️ 开发命令

```bash
make install      # 安装依赖
make test         # 运行单元测试
make test-unit    # 单元测试（含覆盖率）
make lint         # ruff 代码检查
make format       # ruff 代码格式化
make type-check   # mypy 类型检查
make interactive  # 启动交互模式
make help         # 查看所有命令
```

## 📄 许可证

MIT License
