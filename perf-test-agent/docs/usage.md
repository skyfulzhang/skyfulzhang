# 使用指南

## 快速开始

### 1. 克隆仓库并安装依赖

```bash
git clone https://github.com/skyfulzhang/skyfulzhang
cd skyfulzhang/perf-test-agent
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入真实配置
vim .env
```

必填配置项：
- `GITHUB_TOKEN` - GitHub Personal Access Token（需要 `repo` 和 `workflow` 权限）
- `GITHUB_REPO_OWNER` - 仓库所有者
- `GITHUB_REPO_NAME` - 仓库名称
- `OPENAI_API_KEY` - OpenAI API Key（或配置 Azure / Ollama）

### 3. 运行测试

```bash
# 执行完整性能测试流水线
python -m agent.main run-test https://httpbin.org --type load

# 交互式模式
python -m agent.main interactive

# 列出仓库中的脚本
python -m agent.main list-scripts

# 查看最近运行记录
python -m agent.main list-runs
```

---

## CLI 命令详解

### `run-test` - 执行性能测试

```bash
python -m agent.main run-test <URL> [OPTIONS]

参数：
  URL                目标 URL（必填）

选项：
  --type, -t         测试类型 (load/stress/spike/soak/api，默认: load)
  --req, -r          补充测试要求（自然语言描述）
  --branch, -b       工作分支（默认: perf-test/auto）
  --async            异步模式：触发后不等待结果
  --verbose, -v      显示详细日志

示例：
  # 基础负载测试
  python -m agent.main run-test https://api.example.com/users

  # 指定测试类型和要求
  python -m agent.main run-test https://api.example.com \
    --type stress \
    --req "模拟黑色星期五大促流量，预期峰值 1000 并发" \
    --branch perf-test/black-friday
```

### `analyze` - 分析报告

```bash
python -m agent.main analyze <SCRIPT_PATH> [OPTIONS]

参数：
  SCRIPT_PATH        脚本路径，如 k6_scripts/load_test.js

选项：
  --branch, -b       分支（默认: main）

示例：
  python -m agent.main analyze k6_scripts/templates/http_load_test.js
```

### `compare` - 对比报告

```bash
python -m agent.main compare <BASELINE_PATH> <CURRENT_PATH> [OPTIONS]

示例：
  python -m agent.main compare \
    k6_scripts/reports/baseline_20241201_summary.json \
    k6_scripts/reports/current_20241215_summary.json
```

### `interactive` - 交互式模式

```bash
python -m agent.main interactive

# 进入后可以自然语言对话：
# > 帮我测试 https://api.example.com 的接口性能
# > 分析上次的测试结果并给出优化建议
# > 生成一个针对登录接口的压力测试脚本
```

---

## GitHub Actions 配置

### 手动触发测试

在 GitHub 仓库页面 Actions → K6 Performance Test → Run workflow：

| 参数 | 描述 | 示例 |
|------|------|------|
| `script_path` | k6 脚本路径 | `perf-test-agent/k6_scripts/templates/http_load_test.js` |
| `vus` | 并发用户数 | `10` |
| `duration` | 测试时长 | `30s`, `5m` |
| `test_name` | 测试名称（影响报告命名） | `api-load-test` |
| `base_url` | 目标 URL | `https://api.example.com` |

### 定时测试

`k6-schedule-test.yml` 每天 UTC 02:00 自动执行：
- 矩阵策略：并行测试 `load-test` 和 `api-test` 两个场景
- 失败时自动创建 GitHub Issue（标签：`performance`, `automated`）

### 测试报告

报告自动保存到脚本同目录的 `reports/` 子目录：
- `reports/{test_name}_{timestamp}_summary.json` - k6 原始 JSON 数据
- `reports/{test_name}_{timestamp}_report.html` - 可视化 HTML 报告
- Artifact：`k6-reports-{test_name}-{run_id}` (保留 30 天)

---

## 测试类型说明

| 类型 | 脚本 | 适用场景 |
|------|------|----------|
| `load` | `http_load_test.js` | 验证正常负载下的性能，日常回归测试 |
| `stress` | `stress_test.js` | 超负荷测试，找系统断点 |
| `spike` | `spike_test.js` | 突发流量测试，如活动开始瞬间 |
| `soak` | `soak_test.js` | 长时间稳定运行，检测内存泄漏 |
| `api` | `api_test.js` | API 功能正确性 + 性能综合测试 |

---

## 报告解读

### 关键指标

| 指标 | 说明 | 推荐值 |
|------|------|--------|
| P95 响应时间 | 95% 请求的响应时间 | < 500ms |
| P99 响应时间 | 99% 请求的响应时间 | < 1000ms |
| 错误率 | 失败请求比例 | < 1% |
| RPS | 每秒请求数 | 根据业务需求 |

### 性能评级

- 🟢 **PASS（优秀）**: 所有阈值通过，P95 < 300ms，错误率 < 0.5%
- 🟡 **PASS（达标）**: 所有阈值通过，P95 < 500ms，错误率 < 1%
- 🟠 **WARN（需关注）**: 部分指标接近阈值
- 🔴 **FAIL（不合格）**: 有阈值未通过，或错误率 > 5%

---

## 常见问题 FAQ

**Q: 如何配置不同的 LLM 提供商？**

A: 修改 `.env` 中的 `LLM_PROVIDER`：
- `openai` + `OPENAI_API_KEY`
- `azure` + `AZURE_OPENAI_*` 系列配置
- `ollama` + `OLLAMA_BASE_URL` + `OLLAMA_MODEL`（本地运行）

**Q: GitHub Actions 触发失败，提示权限不足？**

A: 确保 GitHub Token 具有以下权限：
- `repo`（读写仓库）
- `workflow`（触发 workflow）

**Q: 如何自定义测试阈值？**

A: 在 `K6TestConfig` 的 `thresholds` 字段中配置：
```python
thresholds={
    "http_req_duration": ["p(95)<300", "p(99)<800"],
    "http_req_failed": ["rate<0.005"],
}
```

**Q: 定时测试的 Issue 如何关闭？**

A: 修复性能问题后手动关闭 Issue，或在下次成功运行后自动更新。

**Q: 如何在本地运行 k6 脚本？**

A: 安装 k6 后直接运行：
```bash
k6 run k6_scripts/templates/http_load_test.js \
  -e K6_BASE_URL=https://api.example.com \
  -e K6_VUS=5 \
  -e K6_DURATION=30s
```
