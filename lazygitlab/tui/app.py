"""LazyGitLabApp — TUI Application メインアプリクラス。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from lazygitlab.infrastructure.git_detector import GitRepoDetector
from lazygitlab.infrastructure.logger import get_logger
from lazygitlab.models import AppConfig
from lazygitlab.services import CommentService, GitLabClient, MRService
from lazygitlab.services.exceptions import LazyGitLabAPIError
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
        Binding("e", "open_in_editor", "Editor"),
        Binding("left_square_bracket", "toggle_sidebar", "Toggle Sidebar"),
    ]

    def __init__(self, config: AppConfig, initial_mr_id: int | None = None) -> None:
        super().__init__()
        self._config = config
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

        mr_panel = MRListPanel(self._mr_service)
        content_panel = ContentPanel(self._mr_service, self._comment_service)
        content_panel.set_editor_command(self._config.editor)

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
            async with self.suspend():
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

    def action_quit(self) -> None:
        self.exit()
