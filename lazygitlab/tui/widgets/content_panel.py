"""ContentPanel — 右ペインのコンテンツ表示ウィジェット。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import RichLog, Static

from lazygitlab.infrastructure.logger import get_logger
from lazygitlab.models import CommentContext, CommentType, Discussion
from lazygitlab.services import CommentService, MRService
from lazygitlab.services.exceptions import LazyGitLabAPIError
from lazygitlab.tui.entities import ContentViewState, DiffViewMode
from lazygitlab.tui.messages import CommentPosted, ShowDiff, ShowOverview
from lazygitlab.tui.screens.comment_dialog import CommentDialog
from lazygitlab.tui.screens.error_dialog import ErrorDialog

_logger = get_logger(__name__)

# 差分行の Rich マークアップカラー
_DIFF_ADD_STYLE = "on #1a3a1a"
_DIFF_REMOVE_STYLE = "on #3a1a1a"
_DIFF_HUNK_STYLE = "bold #6688cc"


def _format_diff_line(line: str) -> str:
    """差分の1行を Rich マークアップでフォーマットする。"""
    if line.startswith("@@"):
        return f"[{_DIFF_HUNK_STYLE}]{line}[/]"
    if line.startswith("+") and not line.startswith("+++"):
        escaped = line.replace("[", r"\[")
        return f"[{_DIFF_ADD_STYLE}]{escaped}[/]"
    if line.startswith("-") and not line.startswith("---"):
        escaped = line.replace("[", r"\[")
        return f"[{_DIFF_REMOVE_STYLE}]{escaped}[/]"
    return line.replace("[", r"\[")


def _get_comment_lines(discussions: list[Discussion]) -> set[int]:
    """インラインコメントが付いている行番号の集合を返す。"""
    lines: set[int] = set()
    for disc in discussions:
        for note in disc.notes:
            if note.position is not None:
                if note.position.new_line is not None:
                    lines.add(note.position.new_line)
                elif note.position.old_line is not None:
                    lines.add(note.position.old_line)
    return lines


def _build_overview_text(mr_detail, discussions: list[Discussion]) -> str:
    """MR詳細とディスカッションからOverview表示テキストを構築する。"""
    lines: list[str] = []
    lines.append(f"# !{mr_detail.iid} {mr_detail.title}")
    lines.append("")
    lines.append("| Field      | Value                          |")
    lines.append("|------------|-------------------------------|")
    lines.append(f"| Author     | {mr_detail.author}            |")
    lines.append(f"| Assignee   | {mr_detail.assignee or '—'}   |")
    lines.append(f"| Status     | {mr_detail.status}            |")
    lines.append(f"| Labels     | {', '.join(mr_detail.labels) or '—'} |")
    lines.append(f"| Milestone  | {mr_detail.milestone or '—'}  |")
    lines.append(f"| Pipeline   | {mr_detail.pipeline_status or '—'} |")
    lines.append(f"| URL        | {mr_detail.web_url}           |")
    lines.append(f"| Created    | {mr_detail.created_at}        |")
    lines.append(f"| Updated    | {mr_detail.updated_at}        |")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    lines.append(mr_detail.description or "(no description)")
    lines.append("")
    lines.append(f"## Discussions ({len(discussions)})")
    for disc in discussions:
        for i, note in enumerate(disc.notes):
            prefix = "  " if i > 0 else ""
            pos_info = ""
            if note.position is not None:
                line_no = note.position.new_line or note.position.old_line
                pos_info = f" [{note.position.file_path}:{line_no}]"
            lines.append(f"{prefix}**{note.author}**{pos_info} ({note.created_at})")
            for body_line in note.body.splitlines():
                lines.append(f"{prefix}  {body_line}")
            lines.append("")
    return "\n".join(lines)


class ContentPanel(Widget):
    """右ペイン: Overview・差分をレンダリングするウィジェット。"""

    BINDINGS = [
        Binding("t", "toggle_diff_mode", "Toggle unified/side-by-side"),
        Binding("c", "add_comment", "Add Comment"),
    ]

    DEFAULT_CSS = """
    ContentPanel {
        width: 1fr;
        height: 100%;
    }
    """

    def __init__(self, mr_service: MRService, comment_service: CommentService) -> None:
        super().__init__()
        self._mr_service = mr_service
        self._comment_service = comment_service
        self._view_state = ContentViewState.EMPTY
        self._diff_mode = DiffViewMode.UNIFIED
        self._current_mr_iid: int | None = None
        self._current_file_path: str | None = None
        self._selected_line: int | None = None
        self._selected_line_type: str = "new"
        # 差分行リスト（行選択用）
        self._diff_lines: list[str] = []
        self._comment_lines: set[int] = set()
        self._editor_command: str = "vi"

    def compose(self) -> ComposeResult:
        yield Static("Select an MR from the list.", id="empty-hint")
        yield RichLog(id="content-log", highlight=False, markup=True, wrap=False)

    def on_mount(self) -> None:
        self.query_one(RichLog).display = False

    def set_editor_command(self, editor_command: str) -> None:
        self._editor_command = editor_command

    # --- メッセージハンドラ ---

    def on_show_overview(self, message: ShowOverview) -> None:
        self._current_mr_iid = message.mr_iid
        self._current_file_path = None
        self.run_worker(self._load_overview(message.mr_iid), exclusive=True)

    def on_show_diff(self, message: ShowDiff) -> None:
        self._current_mr_iid = message.mr_iid
        self._current_file_path = message.file_path
        self.run_worker(self._load_diff(message.mr_iid, message.file_path), exclusive=True)

    def on_comment_posted(self, message: CommentPosted) -> None:
        if self._current_mr_iid == message.mr_iid:
            if self._current_file_path:
                self.run_worker(
                    self._load_diff(message.mr_iid, self._current_file_path), exclusive=True
                )
            else:
                self.run_worker(self._load_overview(message.mr_iid), exclusive=True)

    # --- ローダー ---

    async def _load_overview(self, mr_iid: int) -> None:
        self._view_state = ContentViewState.LOADING
        self.app.sub_title = f"Loading overview for !{mr_iid}..."
        self._show_log()
        log = self.query_one(RichLog)
        log.clear()
        try:
            mr_detail, discussions = await _gather_two(
                self._mr_service.get_mr_detail(mr_iid),
                self._comment_service.get_discussions(mr_iid),
            )
            text = _build_overview_text(mr_detail, discussions)
            log.clear()
            for line in text.splitlines():
                log.write(line)
            self._view_state = ContentViewState.OVERVIEW
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load overview for !%d: %s", mr_iid, exc.message)
            self._view_state = ContentViewState.ERROR
            await self.app.push_screen(ErrorDialog(exc.message))
        finally:
            self.app.sub_title = ""

    async def _load_diff(self, mr_iid: int, file_path: str) -> None:
        self._view_state = ContentViewState.LOADING
        self.app.sub_title = f"Loading diff for {file_path}..."
        self._show_log()
        log = self.query_one(RichLog)
        log.clear()
        try:
            file_diff, discussions = await _gather_two(
                self._mr_service.get_mr_diff(mr_iid, file_path),
                self._comment_service.get_discussions(mr_iid),
            )
            self._comment_lines = _get_comment_lines(discussions)
            self._render_diff(file_diff.diff, file_path)
            self._view_state = ContentViewState.DIFF
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load diff for !%d %s: %s", mr_iid, file_path, exc.message)
            self._view_state = ContentViewState.ERROR
            await self.app.push_screen(ErrorDialog(exc.message))
        finally:
            self.app.sub_title = ""

    def _render_diff(self, diff_text: str, file_path: str) -> None:
        """差分テキストをRichLogにレンダリングする。"""
        log = self.query_one(RichLog)
        log.clear()

        if self._diff_mode == DiffViewMode.UNIFIED:
            self._render_unified(log, diff_text, file_path)
        else:
            self._render_side_by_side(log, diff_text, file_path)

    def _render_unified(self, log: RichLog, diff_text: str, file_path: str) -> None:
        """unified差分を表示する。"""
        lines = diff_text.splitlines()
        self._diff_lines = lines
        # 行番号追跡（new行）
        new_line_no = 0
        hunk_new_start = 0

        for i, line in enumerate(lines):
            # ハンクヘッダーから行番号を解析する
            if line.startswith("@@"):
                import re

                m = re.search(r"\+(\d+)", line)
                if m:
                    hunk_new_start = int(m.group(1))
                    new_line_no = hunk_new_start - 1
                comment_flag = ""
            elif line.startswith("+") and not line.startswith("+++"):
                new_line_no += 1
                comment_flag = " 💬" if new_line_no in self._comment_lines else ""
            elif line.startswith("-") and not line.startswith("---"):
                comment_flag = ""
            else:
                new_line_no += 1
                comment_flag = " 💬" if new_line_no in self._comment_lines else ""

            formatted = _format_diff_line(line)
            if comment_flag:
                formatted = formatted + f"[yellow]{comment_flag}[/yellow]"
            log.write(formatted)

    def _render_side_by_side(self, log: RichLog, diff_text: str, file_path: str) -> None:
        """side-by-side差分を表示する（左: old / 右: new）。"""
        lines = diff_text.splitlines()
        self._diff_lines = lines
        old_lines: list[str] = []
        new_lines: list[str] = []

        for line in lines:
            if line.startswith("@@"):
                # セパレーターとしてハンクヘッダを表示
                log.write(f"[{_DIFF_HUNK_STYLE}]{line}[/]")
                # バッファをフラッシュ
                _flush_side_by_side(log, old_lines, new_lines)
                old_lines, new_lines = [], []
            elif line.startswith("-") and not line.startswith("---"):
                old_lines.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])
            else:
                _flush_side_by_side(log, old_lines, new_lines)
                old_lines, new_lines = [], []
                log.write(line.replace("[", r"\["))

        _flush_side_by_side(log, old_lines, new_lines)

    def _show_log(self) -> None:
        self.query_one("#empty-hint").display = False
        self.query_one(RichLog).display = True

    def get_selected_line(self) -> tuple[str, int] | None:
        """現在選択中の (file_path, line_number) を返す。選択なしはNone。"""
        if (
            self._view_state == ContentViewState.DIFF
            and self._current_file_path is not None
            and self._selected_line is not None
        ):
            return (self._current_file_path, self._selected_line)
        return None

    # --- アクション ---

    def action_toggle_diff_mode(self) -> None:
        if self._view_state != ContentViewState.DIFF:
            return
        self._diff_mode = (
            DiffViewMode.SIDE_BY_SIDE
            if self._diff_mode == DiffViewMode.UNIFIED
            else DiffViewMode.UNIFIED
        )
        if self._current_mr_iid is not None and self._current_file_path is not None:
            self.run_worker(
                self._load_diff(self._current_mr_iid, self._current_file_path),
                exclusive=True,
            )

    async def action_add_comment(self) -> None:
        if self._view_state == ContentViewState.DIFF:
            if self._current_mr_iid is None or self._current_file_path is None:
                return
            line = self._selected_line or 1
            context = CommentContext(
                mr_iid=self._current_mr_iid,
                comment_type=CommentType.INLINE,
                file_path=self._current_file_path,
                line=line,
                line_type=self._selected_line_type,
            )
        elif self._view_state == ContentViewState.OVERVIEW:
            if self._current_mr_iid is None:
                return
            context = CommentContext(
                mr_iid=self._current_mr_iid,
                comment_type=CommentType.NOTE,
            )
        else:
            return

        await self.app.push_screen(
            CommentDialog(context, self._comment_service, self._editor_command)
        )

    async def clear_content(self) -> None:
        """コンテンツをクリアして初期状態に戻す。"""
        self._view_state = ContentViewState.EMPTY
        self._current_mr_iid = None
        self._current_file_path = None
        self._selected_line = None
        self._diff_lines = []
        log = self.query_one(RichLog)
        log.clear()
        log.display = False
        self.query_one("#empty-hint").display = True


def _flush_side_by_side(log: RichLog, old_lines: list[str], new_lines: list[str]) -> None:
    """side-by-side バッファをフラッシュして表示する。"""
    max_len = max(len(old_lines), len(new_lines))
    for i in range(max_len):
        left = old_lines[i] if i < len(old_lines) else ""
        right = new_lines[i] if i < len(new_lines) else ""
        left_fmt = left.replace("[", r"\[")
        right_fmt = right.replace("[", r"\[")
        log.write(f"[{_DIFF_REMOVE_STYLE}]{left_fmt:<50}[/]  [{_DIFF_ADD_STYLE}]{right_fmt}[/]")


async def _gather_two(coro1, coro2):
    """2つのコルーチンを並行実行して結果のタプルを返す。"""
    import asyncio

    result1, result2 = await asyncio.gather(coro1, coro2)
    return result1, result2
