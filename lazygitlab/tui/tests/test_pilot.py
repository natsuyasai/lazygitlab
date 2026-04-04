"""Textual Pilot テスト — 基本ケースのヘッドレステスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lazygitlab.models import AppConfig
from lazygitlab.services.types import PaginatedResult
from lazygitlab.tui.app import LazyGitLabApp
from lazygitlab.tui.screens.error_dialog import ErrorDialog
from lazygitlab.tui.screens.help_screen import HelpScreen


def _make_config() -> AppConfig:
    return AppConfig(
        gitlab_url="https://gitlab.example.com",
        token="test-token",
        editor="vi",
    )


def _make_mock_services():
    """MRService と CommentService のモックを生成する。"""
    empty_result = PaginatedResult(items=[], has_next_page=False, next_page=None)

    mr_service = MagicMock()
    mr_service.load = AsyncMock()
    mr_service.get_assigned_to_me = AsyncMock(return_value=empty_result)
    mr_service.get_created_by_me = AsyncMock(return_value=empty_result)
    mr_service.get_unassigned = AsyncMock(return_value=empty_result)
    mr_service.get_assigned_to_others = AsyncMock(return_value=empty_result)
    mr_service.invalidate_cache = MagicMock()

    comment_service = MagicMock()
    comment_service.load = AsyncMock()
    comment_service.invalidate_cache = MagicMock()

    return mr_service, comment_service


@pytest.fixture
def mock_app():
    """GitLab接続をモックしたLazyGitLabAppインスタンスを生成するファクトリ。"""
    config = _make_config()
    app = LazyGitLabApp(config=config, initial_mr_id=None)
    return app


@pytest.mark.asyncio
async def test_app_quit():
    """q キーでアプリが終了することを確認する。"""
    config = _make_config()
    mr_service, comment_service = _make_mock_services()

    with (
        patch("lazygitlab.tui.app.GitLabClient") as mock_client_cls,
        patch("lazygitlab.tui.app.MRService", return_value=mr_service),
        patch("lazygitlab.tui.app.CommentService", return_value=comment_service),
        patch("lazygitlab.tui.app.GitRepoDetector") as mock_detector_cls,
    ):
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_detector = MagicMock()
        mock_detector.get_project_info.return_value = MagicMock(project_path="group/project")
        mock_detector_cls.return_value = mock_detector

        app = LazyGitLabApp(config=config, initial_mr_id=None)
        async with app.run_test() as pilot:
            await pilot.press("q")
            assert app.is_running is False


@pytest.mark.asyncio
async def test_help_screen_opens():
    """? キーで HelpScreen が表示されることを確認する。"""
    config = _make_config()
    mr_service, comment_service = _make_mock_services()

    with (
        patch("lazygitlab.tui.app.GitLabClient") as mock_client_cls,
        patch("lazygitlab.tui.app.MRService", return_value=mr_service),
        patch("lazygitlab.tui.app.CommentService", return_value=comment_service),
        patch("lazygitlab.tui.app.GitRepoDetector") as mock_detector_cls,
    ):
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_detector = MagicMock()
        mock_detector.get_project_info.return_value = MagicMock(project_path="group/project")
        mock_detector_cls.return_value = mock_detector

        app = LazyGitLabApp(config=config, initial_mr_id=None)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            # HelpScreen がスタックに積まれていることを確認
            assert isinstance(app.screen, HelpScreen)
            # Escape で閉じる
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_sidebar_toggle():
    """[ キーでサイドバーのトグルが動作することを確認する。"""
    config = _make_config()
    mr_service, comment_service = _make_mock_services()

    with (
        patch("lazygitlab.tui.app.GitLabClient") as mock_client_cls,
        patch("lazygitlab.tui.app.MRService", return_value=mr_service),
        patch("lazygitlab.tui.app.CommentService", return_value=comment_service),
        patch("lazygitlab.tui.app.GitRepoDetector") as mock_detector_cls,
    ):
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_detector = MagicMock()
        mock_detector.get_project_info.return_value = MagicMock(project_path="group/project")
        mock_detector_cls.return_value = mock_detector

        app = LazyGitLabApp(config=config, initial_mr_id=None)
        async with app.run_test() as pilot:
            assert app._sidebar_visible is True
            await pilot.press("left_square_bracket")
            assert app._sidebar_visible is False
            await pilot.press("left_square_bracket")
            assert app._sidebar_visible is True


@pytest.mark.asyncio
async def test_error_dialog_shows_on_connection_failure():
    """GitLab接続失敗時にErrorDialogが表示されることを確認する。"""
    from lazygitlab.services.exceptions import GitLabConnectionError

    config = _make_config()

    with (
        patch("lazygitlab.tui.app.GitLabClient") as mock_client_cls,
        patch("lazygitlab.tui.app.GitRepoDetector") as mock_detector_cls,
    ):
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(side_effect=GitLabConnectionError("Connection failed"))
        mock_client_cls.return_value = mock_client

        mock_detector = MagicMock()
        mock_detector.get_project_info.return_value = MagicMock(project_path="group/project")
        mock_detector_cls.return_value = mock_detector

        app = LazyGitLabApp(config=config, initial_mr_id=None)
        async with app.run_test() as pilot:
            # ErrorDialog がスタックに積まれていることを確認
            assert isinstance(app.screen, ErrorDialog)
            # OK ボタンで閉じる
            await pilot.press("enter")


@pytest.mark.asyncio
async def test_error_dialog_dismiss():
    """ErrorDialogが表示され、OKボタンで閉じることができることを確認する。"""

    # ErrorDialog をスタンドアロンでテストする方式
    class _TestApp(LazyGitLabApp):
        async def on_mount(self) -> None:
            await self.push_screen(ErrorDialog("Test error message"))

    config = _make_config()
    test_app = _TestApp(config=config)
    async with test_app.run_test() as pilot:
        assert isinstance(test_app.screen, ErrorDialog)
        await pilot.press("enter")
        # ErrorDialog が閉じられていることを確認（メインスクリーンに戻る）
        assert not isinstance(test_app.screen, ErrorDialog)
