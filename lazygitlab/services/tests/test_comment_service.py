"""lazygitlab.services.comment_service のユニットテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lazygitlab.models import AppConfig
from lazygitlab.services.comment_service import CommentService
from lazygitlab.services.exceptions import (
    EmptyCommentError,
)
from lazygitlab.services.gitlab_client import GitLabClient


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(gitlab_url="https://gitlab.example.com", token="glpat-test")


@pytest.fixture
def mock_client(config: AppConfig) -> MagicMock:
    client = MagicMock(spec=GitLabClient)
    client._config = config
    client.get_project = AsyncMock(return_value=MagicMock())
    client._wrap_api_error = MagicMock(side_effect=lambda e: e)
    return client


@pytest.fixture
async def service(mock_client: MagicMock) -> CommentService:
    svc = CommentService(mock_client, "group/project")
    await svc.load()
    return svc


def _make_raw_discussion(
    discussion_id: str = "abc123",
    notes: list[dict] | None = None,
) -> MagicMock:
    raw = MagicMock()
    raw.id = discussion_id
    raw.attributes = {
        "notes": notes
        or [
            {
                "id": 1,
                "author": {"username": "alice"},
                "body": "Hello",
                "created_at": "2026-01-01T00:00:00Z",
                "system": False,
                "position": None,
            }
        ]
    }
    return raw


class TestGetDiscussions:
    async def test_returns_discussions(self, service: CommentService) -> None:
        raw = _make_raw_discussion()

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=MagicMock())
        service._project.mergerequests.get.return_value.discussions.list = MagicMock(
            return_value=[raw]
        )
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await service.get_discussions(1)
        assert len(result) == 1
        assert result[0].id == "abc123"
        assert result[0].notes[0].author == "alice"

    async def test_excludes_system_notes(self, service: CommentService) -> None:
        raw = _make_raw_discussion(
            notes=[
                {
                    "id": 1,
                    "author": {"username": "gitlab"},
                    "body": "merged this MR",
                    "created_at": "2026-01-01T00:00:00Z",
                    "system": True,
                    "position": None,
                }
            ]
        )

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=MagicMock())
        service._project.mergerequests.get.return_value.discussions.list = MagicMock(
            return_value=[raw]
        )
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            result = await service.get_discussions(1)
        assert len(result) == 0

    async def test_cache_hit(self, service: CommentService) -> None:
        raw = _make_raw_discussion()

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=MagicMock())
        service._project.mergerequests.get.return_value.discussions.list = MagicMock(
            return_value=[raw]
        )
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            r1 = await service.get_discussions(1)
            r2 = await service.get_discussions(1)
        assert r1 is r2


class TestValidateBody:
    def test_empty_raises(self, service: CommentService) -> None:
        with pytest.raises(EmptyCommentError):
            service._validate_body("")

    def test_whitespace_only_raises(self, service: CommentService) -> None:
        with pytest.raises(EmptyCommentError):
            service._validate_body("   ")

    def test_valid_body(self, service: CommentService) -> None:
        service._validate_body("valid comment")  # 例外なし


class TestAddNote:
    async def test_empty_body_raises(self, service: CommentService) -> None:
        with pytest.raises(EmptyCommentError):
            await service.add_note(1, "")

    async def test_add_note_success(self, service: CommentService) -> None:
        mock_note = MagicMock()
        mock_note.attributes = {
            "id": 99,
            "author": {"username": "me"},
            "body": "my note",
            "created_at": "2026-01-01T00:00:00Z",
            "position": None,
        }
        mock_mr = MagicMock()
        mock_mr.notes.create = MagicMock(return_value=mock_note)

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=mock_mr)
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            note = await service.add_note(1, "my note")
        assert note.id == 99
        assert note.author == "me"

    async def test_invalidates_cache_after_add(self, service: CommentService) -> None:
        service._discussions_cache.set(1, [])  # キャッシュに仕込む
        mock_note = MagicMock()
        mock_note.attributes = {
            "id": 1,
            "author": {"username": "me"},
            "body": "x",
            "created_at": "",
            "position": None,
        }
        mock_mr = MagicMock()
        mock_mr.notes.create = MagicMock(return_value=mock_note)

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=mock_mr)
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            await service.add_note(1, "x")
        assert service._discussions_cache.get(1) is None


class TestReplyToDiscussion:
    async def test_empty_body_raises(self, service: CommentService) -> None:
        with pytest.raises(EmptyCommentError):
            await service.reply_to_discussion(1, "disc-id", "")

    async def test_reply_success(self, service: CommentService) -> None:
        mock_note = MagicMock()
        mock_note.attributes = {
            "id": 55,
            "author": {"username": "bob"},
            "body": "reply text",
            "created_at": "2026-01-02T00:00:00Z",
            "position": None,
        }
        mock_discussion = MagicMock()
        mock_discussion.notes.create = MagicMock(return_value=mock_note)
        mock_mr = MagicMock()
        mock_mr.discussions.get = MagicMock(return_value=mock_discussion)

        async def mock_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service._project.mergerequests.get = MagicMock(return_value=mock_mr)
        with patch("asyncio.to_thread", side_effect=mock_to_thread):
            note = await service.reply_to_discussion(1, "disc-abc", "reply text")
        assert note.id == 55
        assert note.body == "reply text"


class TestConvertPosition:
    def test_none_returns_none(self, service: CommentService) -> None:
        assert service._convert_position(None) is None

    def test_both_none_returns_none(self, service: CommentService) -> None:
        assert service._convert_position({"new_line": None, "old_line": None}) is None

    def test_new_line_set(self, service: CommentService) -> None:
        pos = service._convert_position({"new_path": "foo.py", "new_line": 10, "old_line": None})
        assert pos is not None
        assert pos.new_line == 10
        assert pos.old_line is None
