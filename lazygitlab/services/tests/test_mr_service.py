"""lazygitlab.services.mr_service のユニットテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lazygitlab.models import AppConfig
from lazygitlab.services.exceptions import FileNotFoundInMRError
from lazygitlab.services.gitlab_client import CurrentUser, GitLabClient
from lazygitlab.services.mr_service import MRService
from lazygitlab.services.types import PaginatedResult


def _make_mr(
    iid: int = 1,
    title: str = "Test MR",
    author_username: str = "alice",
    assignee_username: str | None = None,
    assignee_id: int | None = None,
    state: str = "opened",
    labels: list[str] | None = None,
    updated_at: str = "2026-01-01T00:00:00Z",
) -> MagicMock:
    mr = MagicMock()
    mr.iid = iid
    mr.title = title
    mr.author = {"username": author_username}
    mr.assignee = {"username": assignee_username, "id": assignee_id} if assignee_username else None
    mr.state = state
    mr.labels = labels or []
    mr.updated_at = updated_at
    mr.description = "desc"
    mr.milestone = None
    mr.head_pipeline = None
    mr.web_url = f"https://gitlab.example.com/mr/{iid}"
    mr.created_at = "2026-01-01T00:00:00Z"
    mr.diff_refs = {"base_sha": "aaa", "head_sha": "bbb", "start_sha": "ccc"}
    return mr


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(gitlab_url="https://gitlab.example.com", token="glpat-test")


@pytest.fixture
def mock_client(config: AppConfig) -> MagicMock:
    client = MagicMock(spec=GitLabClient)
    client._config = config
    client.get_project = AsyncMock(return_value=MagicMock())
    client.get_current_user = AsyncMock(return_value=CurrentUser(id=10, username="me"))
    client._wrap_api_error = MagicMock(side_effect=lambda e: e)
    return client


@pytest.fixture
async def service(mock_client: MagicMock) -> MRService:
    svc = MRService(mock_client, "group/project")
    await svc.load()
    return svc


class TestMRServiceLoad:
    async def test_load_sets_project_and_user(self, mock_client: MagicMock) -> None:
        svc = MRService(mock_client, "group/project")
        await svc.load()
        assert svc._project is not None
        assert svc._current_user_id == 10


class TestGetAssignedToMe:
    async def test_returns_paginated_result(self, service: MRService) -> None:
        mr = _make_mr(iid=1, assignee_username="me", assignee_id=10)
        mock_list = [mr]
        mock_list._next_url = None  # type: ignore[attr-defined]
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_list)):
            result = await service.get_assigned_to_me()
        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 1
        assert result.items[0].iid == 1
        assert result.has_next_page is False


class TestGetAssignedToOthers:
    async def test_excludes_current_user(self, service: MRService) -> None:
        mr_me = _make_mr(iid=1, assignee_username="me", assignee_id=10)
        mr_other = _make_mr(iid=2, assignee_username="bob", assignee_id=20)
        mock_list = [mr_me, mr_other]
        mock_list._next_url = None  # type: ignore[attr-defined]
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_list)):
            result = await service.get_assigned_to_others()
        assert len(result.items) == 1
        assert result.items[0].iid == 2


class TestConvertToSummary:
    def test_basic_conversion(self, service: MRService) -> None:
        mr = _make_mr(iid=5, title="My MR", author_username="alice")
        summary = service._convert_to_summary(mr)
        assert summary.iid == 5
        assert summary.title == "My MR"
        assert summary.author == "alice"
        assert summary.assignee is None

    def test_with_assignee(self, service: MRService) -> None:
        mr = _make_mr(assignee_username="bob", assignee_id=20)
        summary = service._convert_to_summary(mr)
        assert summary.assignee == "bob"


class TestConvertToDetail:
    def test_basic_conversion(self, service: MRService) -> None:
        mr = _make_mr(iid=3)
        detail = service._convert_to_detail(mr)
        assert detail.iid == 3
        assert detail.description == "desc"
        assert detail.milestone is None
        assert detail.pipeline_status is None

    def test_with_milestone(self, service: MRService) -> None:
        mr = _make_mr()
        mr.milestone = {"title": "v1.0"}
        detail = service._convert_to_detail(mr)
        assert detail.milestone == "v1.0"

    def test_with_pipeline(self, service: MRService) -> None:
        mr = _make_mr()
        mr.head_pipeline = {"status": "passed"}
        detail = service._convert_to_detail(mr)
        assert detail.pipeline_status == "passed"


class TestGetMrDetail:
    async def test_cache_miss_then_hit(self, service: MRService) -> None:
        mr = _make_mr(iid=7)
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mr)):
            detail1 = await service.get_mr_detail(7)
        # 2回目はキャッシュから（to_thread呼ばれない）
        detail2 = service._detail_cache.get(7)
        assert detail1.iid == 7
        assert detail2 is not None
        assert detail2.iid == 7

    async def test_invalidate_cache(self, service: MRService) -> None:
        mr = _make_mr(iid=7)
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mr)):
            await service.get_mr_detail(7)
        service.invalidate_cache(7)
        assert service._detail_cache.get(7) is None

    async def test_invalidate_all_cache(self, service: MRService) -> None:
        mr = _make_mr(iid=7)
        with patch("asyncio.to_thread", new=AsyncMock(return_value=mr)):
            await service.get_mr_detail(7)
        service.invalidate_cache()
        assert service._detail_cache.get(7) is None


class TestGetMrDiff:
    async def test_file_found(self, service: MRService) -> None:
        mr = MagicMock()
        mr.changes = MagicMock(
            return_value={
                "changes": [
                    {
                        "old_path": "foo.py",
                        "new_path": "foo.py",
                        "diff": "@@ -1 +1 @@ foo",
                        "new_file": False,
                        "deleted_file": False,
                        "renamed_file": False,
                    }
                ]
            }
        )

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            service._project.mergerequests.get = MagicMock(return_value=mr)
            diff = await service.get_mr_diff(1, "foo.py")
        assert diff.file_path == "foo.py"
        assert "@@ -1 +1 @@" in diff.diff

    async def test_file_not_found_raises(self, service: MRService) -> None:
        mr = MagicMock()
        mr.changes = MagicMock(return_value={"changes": []})

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            service._project.mergerequests.get = MagicMock(return_value=mr)
            with pytest.raises(FileNotFoundInMRError):
                await service.get_mr_diff(1, "missing.py")
