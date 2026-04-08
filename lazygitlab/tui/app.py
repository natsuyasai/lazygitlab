"""LazyGitLabApp — TUI Application メインアプリクラス。"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Tree

from lazygitlab.infrastructure.config import ConfigManager
from lazygitlab.infrastructure.git_detector import GitRepoDetector
from lazygitlab.infrastructure.logger import get_logger
from lazygitlab.models import AppConfig
from lazygitlab.services import CommentService, GitLabClient, MRService
from lazygitlab.services.exceptions import LazyGitLabAPIError
from lazygitlab.tui.messages import CommentPosted, ShowDiff, ShowOverview
from lazygitlab.tui.screens.error_dialog import ErrorDialog
from lazygitlab.tui.screens.help_screen import HelpScreen
from lazygitlab.tui.widgets.content_panel import ContentPanel
from lazygitlab.tui.widgets.mr_list_panel import MRListPanel

_logger = get_logger(__name__)

_CSS_PATH = Path(__file__).parent / "styles.tcss"


class LazyGitLabApp(App):
    """GitLab MR ブラウザ・コメント TUI アプリケーション。"""

    CSS_PATH = _CSS_PATH

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help"),
        Binding("r", "refresh", "Refresh"),
        Binding("m", "focus_mr_list", "Focus MR"),
        Binding("e", "open_in_editor", "Editor", priority=True),
        Binding("left_square_bracket", "toggle_sidebar", "Toggle Sidebar"),
        Binding("b", "checkout_branch", "Checkout Branch"),
    ]

    def __init__(
        self,
        config: AppConfig,
        config_manager: ConfigManager | None = None,
        initial_mr_id: int | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_manager = config_manager
        self._initial_mr_id = initial_mr_id
        self._sidebar_visible = True
        self._client: GitLabClient | None = None
        self._mr_service: MRService | None = None
        self._comment_service: CommentService | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        # ウィジェットは on_mount で初期化後に置き換えるため、
        # プレースホルダーとして空の状態でマウントする
        with Horizontal(id="main-container"):
            pass
        yield Footer()

    async def on_mount(self) -> None:
        """アプリ起動時にGitLabへ接続し、ウィジェットを初期化する。"""
        self.title = "lazygitlab"
        self.sub_title = "Connecting..."

        try:
            detector = GitRepoDetector()
            project_info = detector.detect(self._config)
            project_path = project_info.project_path

            self._client = GitLabClient(self._config)
            await self._client.connect()

            self._mr_service = MRService(self._client, project_path)
            await self._mr_service.load()

            self._comment_service = CommentService(self._client, project_path)
            await self._comment_service.load()

        except LazyGitLabAPIError as exc:
            _logger.error("Connection failed: %s", exc.message)
            self.sub_title = "Connection failed"
            await self.push_screen(ErrorDialog(exc.message))
            return
        except Exception as exc:
            _logger.exception("Unexpected error during startup")
            self.sub_title = "Startup error"
            await self.push_screen(ErrorDialog(str(exc)))
            return

        self.sub_title = ""

        # main-container 内のウィジェットを正しく生成・マウントする
        container = self.query_one("#main-container")
        # ダミーウィジェットを削除して再生成
        for child in list(container.children):
            await child.remove()

        mr_panel = MRListPanel(self._mr_service, self._comment_service)
        content_panel = ContentPanel(self._mr_service, self._comment_service)
        content_panel.set_editor_command(self._config.editor)
        if self._config.pygments_style:
            content_panel.set_pygments_style(self._config.pygments_style)
        if self._config_manager is not None:
            config_manager = self._config_manager

            def _save_style(style_name: str) -> None:
                config_manager.save_setting("appearance", "pygments_style", style_name)

            content_panel.set_style_save_callback(_save_style)

        await container.mount(mr_panel, content_panel)

        # 初期MR IDが指定されている場合は後で展開する
        if self._initial_mr_id is not None:
            _logger.info("Auto-expanding MR !%d", self._initial_mr_id)

    # --- アクション ---

    async def action_show_help(self) -> None:
        await self.push_screen(HelpScreen())

    async def action_refresh(self) -> None:
        if self._mr_service is None or self._comment_service is None:
            return
        self._mr_service.invalidate_cache()
        self._comment_service.invalidate_cache()

        try:
            mr_panel = self.query_one(MRListPanel)
            await mr_panel.refresh_list()
        except Exception:  # noqa: S110
            pass

        try:
            content_panel = self.query_one(ContentPanel)
            await content_panel.clear_content()
        except Exception:  # noqa: S110
            pass

        _logger.info("Refreshed MR list and cleared cache")

    async def action_open_in_editor(self) -> None:
        """現在表示中のファイルを外部エディタで開く。"""
        try:
            content_panel = self.query_one(ContentPanel)
            location = content_panel.get_selected_line()
        except Exception:
            return

        if location is None:
            return

        file_path, line_no = location
        editor = self._config.editor or "vi"
        _logger.info("Opening editor: %s +%d %s", editor, line_no, file_path)
        try:
            with self.suspend():
                subprocess.run([editor, f"+{line_no}", file_path], check=False)  # noqa: S603
        except FileNotFoundError:
            await self.push_screen(ErrorDialog(f"Editor not found: {editor}"))
        except Exception as exc:
            _logger.error("Editor error: %s", exc)
            await self.push_screen(ErrorDialog(f"Editor error: {exc}"))

    def action_toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        try:
            mr_panel = self.query_one(MRListPanel)
            if self._sidebar_visible:
                mr_panel.remove_class("-hidden")
            else:
                mr_panel.add_class("-hidden")
        except Exception:  # noqa: S110
            pass

    def action_focus_mr_list(self) -> None:
        try:
            mr_panel = self.query_one(MRListPanel)
            tree = mr_panel.query_one(Tree)
            tree.focus()
        except Exception:  # noqa: S110
            pass

    # --- メッセージハンドラ（兄弟ウィジェット間のルーティング） ---

    def on_show_overview(self, message: ShowOverview) -> None:
        """MRListPanel から上がってきた ShowOverview を ContentPanel に転送する。"""
        message.stop()
        try:
            content_panel = self.query_one(ContentPanel)
            content_panel.on_show_overview(message)
        except Exception:  # noqa: S110
            pass

    def on_show_diff(self, message: ShowDiff) -> None:
        """MRListPanel から上がってきた ShowDiff を ContentPanel に転送する。"""
        message.stop()
        try:
            content_panel = self.query_one(ContentPanel)
            content_panel.on_show_diff(message)
        except Exception:  # noqa: S110
            pass

    def on_comment_posted(self, message: CommentPosted) -> None:
        """CommentDialog から上がってきた CommentPosted を ContentPanel に転送する。"""
        message.stop()
        try:
            content_panel = self.query_one(ContentPanel)
            content_panel.on_comment_posted(message)
        except Exception:  # noqa: S110
            pass

    async def action_checkout_branch(self) -> None:
        """選択中の MR のソースブランチをチェックアウトまたはスイッチする。"""
        if self._mr_service is None:
            return
        try:
            mr_panel = self.query_one(MRListPanel)
        except Exception:
            return
        mr_iid = mr_panel.get_selected_mr_iid()
        if mr_iid is None:
            return
        self.run_worker(self._checkout_branch_worker(mr_iid), exclusive=False)

    async def _checkout_branch_worker(self, mr_iid: int) -> None:
        """ブランチのチェックアウト処理を非同期ワーカーとして実行する。"""
        from lazygitlab.infrastructure.git_ops import GitOpsError, checkout_or_switch_branch

        self.sub_title = f"MR !{mr_iid} の情報を取得中..."
        try:
            assert self._mr_service is not None
            detail = await self._mr_service.get_mr_detail(mr_iid)
        except Exception as exc:
            self.sub_title = ""
            await self.push_screen(ErrorDialog(f"MR 情報の取得に失敗しました: {exc}"))
            return

        source_branch = detail.source_branch
        if not source_branch:
            self.sub_title = ""
            await self.push_screen(ErrorDialog("ソースブランチ情報が取得できませんでした。"))
            return

        remote = self._config.remote_name or "origin"
        self.sub_title = f"'{source_branch}' をチェックアウト中..."
        try:
            result = await asyncio.to_thread(checkout_or_switch_branch, source_branch, remote)
            self.notify(result.message)
        except GitOpsError as exc:
            await self.push_screen(ErrorDialog(str(exc)))
        except Exception as exc:
            _logger.exception("Unexpected error during git checkout")
            await self.push_screen(ErrorDialog(f"予期しないエラー: {exc}"))
        finally:
            self.sub_title = ""

    def action_quit(self) -> None:
        self.exit()
