"""
tests/unit/test_github_service.py
GitHubService 单元测试（使用 Mock，不需要真实 GitHub 连接）。
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from agent.services.github_service import GitHubService


@pytest.fixture
def mock_github_service(mock_settings):
    """带 Mock GitHub 客户端的 GitHubService fixture。"""
    with patch("agent.services.github_service.Github") as mock_github_cls:
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        service = GitHubService(mock_settings)
        # 强制设置 _repo 避免懒加载
        service._repo = mock_repo
        service._mock_repo = mock_repo

        yield service, mock_repo


class TestGetOrCreateBranch:
    """get_or_create_branch 方法测试。"""

    def test_returns_existing_branch(self, mock_github_service):
        """分支已存在时应直接返回。"""
        service, mock_repo = mock_github_service
        mock_branch = MagicMock()
        mock_repo.get_branch.return_value = mock_branch

        result = service.get_or_create_branch("existing-branch")
        assert result == mock_branch
        mock_repo.get_branch.assert_called_once_with("existing-branch")

    def test_creates_branch_when_not_found(self, mock_github_service):
        """分支不存在时应创建新分支。"""
        from github.GithubException import GithubException

        service, mock_repo = mock_github_service

        # 第一次调用（目标分支）抛出 404，第二次调用（结果）返回新分支
        not_found_exc = GithubException(status=404, data={"message": "Branch not found"})
        new_branch = MagicMock()

        mock_repo.get_branch.side_effect = [not_found_exc, MagicMock(), new_branch]
        mock_repo.create_git_ref.return_value = MagicMock()
        mock_base_branch = MagicMock()
        mock_base_branch.commit.sha = "abc123"

        # reset side_effect to handle sequential calls
        call_count = [0]
        def get_branch_side_effect(name):
            call_count[0] += 1
            if call_count[0] == 1 and name == "new-branch":
                raise not_found_exc
            elif name == "main":
                return mock_base_branch
            return new_branch

        mock_repo.get_branch.side_effect = get_branch_side_effect

        result = service.get_or_create_branch("new-branch", "main")
        mock_repo.create_git_ref.assert_called_once()


class TestUploadK6Script:
    """upload_k6_script 方法测试。"""

    def test_creates_new_file_when_not_exists(self, mock_github_service):
        """文件不存在时应创建新文件并返回 SHA。"""
        from github.GithubException import GithubException

        service, mock_repo = mock_github_service
        not_found = GithubException(status=404, data={})
        mock_repo.get_contents.side_effect = not_found

        mock_content = MagicMock()
        mock_content.sha = "newsha123"
        mock_repo.create_file.return_value = {"content": mock_content}

        sha = service.upload_k6_script(
            script_content="// k6 script",
            script_path="k6_scripts/test.js",
            branch="main",
            commit_message="add script",
        )
        assert sha == "newsha123"
        mock_repo.create_file.assert_called_once()

    def test_updates_existing_file(self, mock_github_service):
        """文件已存在时应更新并返回新 SHA。"""
        service, mock_repo = mock_github_service

        existing = MagicMock()
        existing.sha = "oldsha"
        mock_repo.get_contents.return_value = existing

        mock_updated = MagicMock()
        mock_updated.sha = "newsha456"
        mock_repo.update_file.return_value = {"content": mock_updated}

        sha = service.upload_k6_script(
            script_content="// updated k6 script",
            script_path="k6_scripts/test.js",
            branch="main",
            commit_message="update script",
        )
        assert sha == "newsha456"
        mock_repo.update_file.assert_called_once()


class TestListK6Scripts:
    """list_k6_scripts 方法测试。"""

    def test_returns_js_files_only(self, mock_github_service):
        """只应返回 .js 文件，排除其他格式。"""
        service, mock_repo = mock_github_service

        js_file = MagicMock()
        js_file.type = "file"
        js_file.name = "load_test.js"
        js_file.path = "k6_scripts/load_test.js"

        json_file = MagicMock()
        json_file.type = "file"
        json_file.name = "report.json"
        json_file.path = "k6_scripts/report.json"

        mock_repo.get_contents.return_value = [js_file, json_file]

        scripts = service.list_k6_scripts("k6_scripts")
        assert "k6_scripts/load_test.js" in scripts
        assert "k6_scripts/report.json" not in scripts

    def test_returns_empty_list_when_directory_not_found(self, mock_github_service):
        """目录不存在时应返回空列表。"""
        from github.GithubException import GithubException

        service, mock_repo = mock_github_service
        mock_repo.get_contents.side_effect = GithubException(status=404, data={})

        scripts = service.list_k6_scripts("nonexistent")
        assert scripts == []


class TestGetFileContent:
    """get_file_content 方法测试。"""

    def test_returns_decoded_content(self, mock_github_service):
        """应返回解码后的文件内容。"""
        import base64

        service, mock_repo = mock_github_service
        content = "// k6 script content"
        encoded = base64.b64encode(content.encode()).decode()

        mock_file = MagicMock()
        mock_file.content = encoded
        mock_repo.get_contents.return_value = mock_file

        result = service.get_file_content("k6_scripts/test.js", "main")
        assert result == content

    def test_raises_value_error_for_directory(self, mock_github_service):
        """路径是目录时应抛出 ValueError。"""
        service, mock_repo = mock_github_service
        # 返回列表表示目录
        mock_repo.get_contents.return_value = [MagicMock(), MagicMock()]

        with pytest.raises(ValueError, match="是目录"):
            service.get_file_content("k6_scripts/", "main")
