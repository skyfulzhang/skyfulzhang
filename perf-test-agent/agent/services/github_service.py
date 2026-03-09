"""
agent/services/github_service.py
GitHub 操作服务 - 使用 PyGitHub 封装完整的 GitHub 操作，线程安全，支持并发调用。
"""

import base64
import io
import threading
import time
import zipfile
from typing import Any, Optional

from github import Github, GithubException
from github.Branch import Branch
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.WorkflowRun import WorkflowRun

from agent.utils.config import Settings
from agent.utils.logger import get_logger
from agent.utils.retry import github_retry

logger = get_logger(__name__)

# 线程局部存储，确保并发安全
_thread_local = threading.local()


class GitHubService:
    """PyGitHub 封装的 GitHub 操作服务。

    提供脚本上传、Workflow 触发与监控、报告保存、PR 创建等完整能力。
    所有方法线程安全（通过 threading.Lock 保护写操作）。

    Args:
        config: 全局配置对象。
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self._client = Github(config.github_token)
        self._repo: Optional[Repository] = None
        self._lock = threading.Lock()

    @property
    def repo(self) -> Repository:
        """懒加载仓库对象（线程安全）。"""
        if self._repo is None:
            with self._lock:
                if self._repo is None:
                    self._repo = self._client.get_repo(
                        f"{self.config.github_repo_owner}/{self.config.github_repo_name}"
                    )
        return self._repo

    # ── 分支管理 ──────────────────────────────────────────────────────────────

    @github_retry()
    def get_or_create_branch(
        self, branch_name: str, base_branch: str = "main"
    ) -> Branch:
        """获取或创建分支。

        Args:
            branch_name: 目标分支名称。
            base_branch: 若需创建分支时，以此为基础分支。

        Returns:
            Branch: 目标分支对象。
        """
        try:
            branch = self.repo.get_branch(branch_name)
            logger.info("branch_exists", branch=branch_name)
            return branch
        except GithubException as exc:
            if exc.status != 404:
                raise
            # 分支不存在，创建新分支
            base = self.repo.get_branch(base_branch)
            ref = self.repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=base.commit.sha,
            )
            logger.info("branch_created", branch=branch_name, base=base_branch)
            return self.repo.get_branch(branch_name)

    # ── 文件操作 ──────────────────────────────────────────────────────────────

    @github_retry()
    def upload_k6_script(
        self,
        script_content: str,
        script_path: str,
        branch: str,
        commit_message: str,
    ) -> str:
        """上传 k6 脚本到 GitHub 仓库。

        若文件已存在则更新，否则创建新文件。

        Args:
            script_content: 脚本内容。
            script_path: 仓库内文件路径，例 ``k6_scripts/load_test.js``。
            branch: 目标分支。
            commit_message: 提交说明。

        Returns:
            str: 文件 SHA（用于后续更新）。
        """
        with self._lock:
            try:
                # 文件已存在，更新
                existing = self.repo.get_contents(script_path, ref=branch)
                result = self.repo.update_file(
                    path=script_path,
                    message=commit_message,
                    content=script_content,
                    sha=existing.sha,  # type: ignore[union-attr]
                    branch=branch,
                )
                sha = result["content"].sha
                logger.info(
                    "script_updated",
                    path=script_path,
                    branch=branch,
                    sha=sha,
                )
            except GithubException as exc:
                if exc.status != 404:
                    raise
                # 文件不存在，创建
                result = self.repo.create_file(
                    path=script_path,
                    message=commit_message,
                    content=script_content,
                    branch=branch,
                )
                sha = result["content"].sha
                logger.info(
                    "script_created",
                    path=script_path,
                    branch=branch,
                    sha=sha,
                )
            return sha

    @github_retry()
    def get_file_content(self, path: str, branch: str = "main") -> str:
        """获取仓库文件内容。

        Args:
            path: 文件路径。
            branch: 分支名称。

        Returns:
            str: 文件文本内容。

        Raises:
            GithubException: 文件不存在时。
        """
        content_file = self.repo.get_contents(path, ref=branch)
        if isinstance(content_file, list):
            raise ValueError(f"路径 {path!r} 是目录，无法获取文件内容")
        decoded = base64.b64decode(content_file.content).decode("utf-8")
        logger.debug("file_fetched", path=path, branch=branch, size=len(decoded))
        return decoded

    @github_retry()
    def save_report_to_repo(
        self,
        report_content: str,
        report_path: str,
        branch: str,
        commit_message: str,
    ) -> None:
        """将测试报告保存到仓库（与脚本同目录）。

        Args:
            report_content: 报告内容（HTML 或 JSON 字符串）。
            report_path: 报告保存路径，例 ``k6_scripts/reports/load_test_report.html``。
            branch: 目标分支。
            commit_message: 提交说明。
        """
        self.upload_k6_script(
            script_content=report_content,
            script_path=report_path,
            branch=branch,
            commit_message=commit_message,
        )
        logger.info("report_saved", path=report_path, branch=branch)

    @github_retry()
    def list_k6_scripts(self, directory: str = "k6_scripts") -> list[str]:
        """列出仓库中指定目录下的所有 k6 脚本文件。

        Args:
            directory: 搜索目录，默认 ``k6_scripts``。

        Returns:
            list[str]: 脚本文件路径列表（仅 .js 文件）。
        """
        try:
            contents = self.repo.get_contents(directory)
        except GithubException as exc:
            if exc.status == 404:
                logger.warning("directory_not_found", directory=directory)
                return []
            raise

        scripts: list[str] = []
        stack = list(contents) if isinstance(contents, list) else [contents]
        while stack:
            item = stack.pop()
            if item.type == "dir":
                sub = self.repo.get_contents(item.path)
                stack.extend(sub if isinstance(sub, list) else [sub])
            elif item.name.endswith(".js"):
                scripts.append(item.path)

        logger.debug("scripts_listed", directory=directory, count=len(scripts))
        return sorted(scripts)

    # ── Workflow 操作 ─────────────────────────────────────────────────────────

    @github_retry()
    def trigger_workflow(
        self,
        workflow_file: str,
        ref: str,
        inputs: dict[str, Any],
    ) -> WorkflowRun:
        """触发 GitHub Actions Workflow（workflow_dispatch 事件）。

        Args:
            workflow_file: Workflow 文件名，例 ``k6-performance-test.yml``。
            ref: 触发分支名。
            inputs: workflow_dispatch 输入参数字典。

        Returns:
            WorkflowRun: 触发后的 WorkflowRun 对象（等待约 3 秒后获取）。

        Raises:
            RuntimeError: 触发后未能找到对应 WorkflowRun。
        """
        workflow = self.repo.get_workflow(workflow_file)
        triggered = workflow.create_dispatch(ref=ref, inputs=inputs)

        if not triggered:
            raise RuntimeError(f"触发 Workflow {workflow_file!r} 失败")

        # 等待 GitHub 创建 run 记录
        time.sleep(3)
        runs = workflow.get_runs(branch=ref)
        for run in runs:
            if run.status in ("queued", "in_progress"):
                logger.info(
                    "workflow_triggered",
                    workflow=workflow_file,
                    run_id=run.id,
                    ref=ref,
                )
                return run

        # fallback：取最新的 run
        latest_run = next(iter(workflow.get_runs()), None)
        if latest_run is None:
            raise RuntimeError("触发 Workflow 后未能找到对应 WorkflowRun")
        return latest_run

    @github_retry()
    def wait_for_workflow_completion(
        self,
        run_id: int,
        timeout_seconds: int,
        poll_interval: int,
    ) -> WorkflowRun:
        """轮询等待 Workflow 完成。

        Args:
            run_id: WorkflowRun ID。
            timeout_seconds: 最大等待时长（秒）。
            poll_interval: 轮询间隔（秒）。

        Returns:
            WorkflowRun: 完成后的 WorkflowRun 对象。

        Raises:
            TimeoutError: 超过 timeout_seconds 仍未完成。
        """
        start_time = time.time()
        elapsed = 0.0

        while elapsed < timeout_seconds:
            run = self.repo.get_workflow_run(run_id)
            logger.info(
                "workflow_polling",
                run_id=run_id,
                status=run.status,
                elapsed_seconds=round(elapsed, 1),
            )

            if run.status == "completed":
                logger.info(
                    "workflow_completed",
                    run_id=run_id,
                    conclusion=run.conclusion,
                    duration=round(elapsed, 1),
                )
                return run

            time.sleep(poll_interval)
            elapsed = time.time() - start_time

        run = self.repo.get_workflow_run(run_id)
        logger.warning(
            "workflow_timeout",
            run_id=run_id,
            timeout_seconds=timeout_seconds,
            last_status=run.status,
        )
        raise TimeoutError(
            f"Workflow run {run_id} 在 {timeout_seconds}s 内未完成，当前状态: {run.status}"
        )

    @github_retry()
    def get_workflow_logs(self, run_id: int) -> str:
        """获取 Workflow 运行日志（纯文本）。

        Args:
            run_id: WorkflowRun ID。

        Returns:
            str: 日志内容（各 step 日志拼接）。
        """
        run = self.repo.get_workflow_run(run_id)
        logs_url = run.logs_url
        import urllib.request

        req = urllib.request.Request(
            logs_url,
            headers={"Authorization": f"token {self.config.github_token}"},
        )
        with urllib.request.urlopen(req) as resp:
            log_bytes = resp.read()

        # logs 是 zip 包，解压提取所有 .txt 文件
        with zipfile.ZipFile(io.BytesIO(log_bytes)) as zf:
            parts: list[str] = []
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    parts.append(zf.read(name).decode("utf-8", errors="replace"))
        return "\n".join(parts)

    @github_retry()
    def download_artifact(self, run_id: int, artifact_name: str) -> bytes:
        """下载 Workflow Artifact（zip 格式）。

        Args:
            run_id: WorkflowRun ID。
            artifact_name: Artifact 名称。

        Returns:
            bytes: zip 文件内容。

        Raises:
            ValueError: 未找到指定 Artifact。
        """
        run = self.repo.get_workflow_run(run_id)
        for artifact in run.get_artifacts():
            if artifact.name == artifact_name:
                import urllib.request

                req = urllib.request.Request(
                    artifact.archive_download_url,
                    headers={"Authorization": f"token {self.config.github_token}"},
                )
                with urllib.request.urlopen(req) as resp:
                    return resp.read()

        raise ValueError(
            f"WorkflowRun {run_id} 中未找到 Artifact: {artifact_name!r}"
        )

    @github_retry()
    def list_workflow_runs(
        self, workflow_file: str, limit: int = 10
    ) -> list[WorkflowRun]:
        """列出最近的 Workflow 运行记录。

        Args:
            workflow_file: Workflow 文件名。
            limit: 最多返回条数。

        Returns:
            list[WorkflowRun]: WorkflowRun 列表（按时间倒序）。
        """
        workflow = self.repo.get_workflow(workflow_file)
        runs = workflow.get_runs()
        result = []
        for i, run in enumerate(runs):
            if i >= limit:
                break
            result.append(run)
        return result

    # ── PR ────────────────────────────────────────────────────────────────────

    @github_retry()
    def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequest:
        """创建 Pull Request。

        Args:
            title: PR 标题。
            body: PR 描述。
            head_branch: 源分支（含优化脚本）。
            base_branch: 目标分支，默认 ``main``。

        Returns:
            PullRequest: 创建的 PR 对象。
        """
        pr = self.repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        logger.info(
            "pull_request_created",
            pr_number=pr.number,
            url=pr.html_url,
            head=head_branch,
            base=base_branch,
        )
        return pr
