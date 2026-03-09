.DEFAULT_GOAL := help

.PHONY: help install install-dev test test-unit test-integration lint format type-check \
        run-test interactive list-scripts list-runs docker-build clean

# ─────────────────────────────────────────
# 帮助
# ─────────────────────────────────────────
help: ## 显示帮助信息
	@awk 'BEGIN {FS = ":.*##"; printf "\n\033[1mperf-test-agent 命令列表\033[0m\n\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─────────────────────────────────────────
# 依赖安装
# ─────────────────────────────────────────
install: ## 安装生产依赖
	pip install -r requirements.txt

install-dev: ## 安装开发依赖（含测试工具）
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov ruff mypy

# ─────────────────────────────────────────
# 测试
# ─────────────────────────────────────────
test: ## 运行所有单元测试
	pytest tests/unit/ -v --tb=short

test-unit: ## 运行单元测试（带覆盖率）
	pytest tests/unit/ -v --cov=agent --cov-report=term-missing --cov-report=html

test-integration: ## 运行集成测试（需要真实 API 密钥）
	pytest tests/integration/ -v --tb=short -m integration

# ─────────────────────────────────────────
# 代码质量
# ─────────────────────────────────────────
lint: ## 运行 ruff 代码检查
	ruff check agent/ tests/

format: ## 运行 ruff 代码格式化
	ruff format agent/ tests/
	ruff check --fix agent/ tests/

type-check: ## 运行 mypy 类型检查
	mypy agent/ --ignore-missing-imports

# ─────────────────────────────────────────
# 运行命令
# ─────────────────────────────────────────
run-test: ## 执行性能测试流水线 (需设置 URL 变量: make run-test URL=https://api.example.com)
	python -m agent.main run-test $(URL) --type load

interactive: ## 启动交互式智能对话模式
	python -m agent.main interactive

list-scripts: ## 列出仓库中的测试脚本
	python -m agent.main list-scripts

list-runs: ## 列出最近的 workflow runs
	python -m agent.main list-runs

# ─────────────────────────────────────────
# Docker
# ─────────────────────────────────────────
docker-build: ## 构建 Docker 镜像
	docker build -t perf-test-agent:latest .

# ─────────────────────────────────────────
# 清理
# ─────────────────────────────────────────
clean: ## 清理构建产物和缓存
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	@echo "✅ 清理完成"
