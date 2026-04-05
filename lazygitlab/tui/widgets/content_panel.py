"""ContentPanel — 右ペインのコンテンツ表示ウィジェット。"""

from __future__ import annotations

import re
from typing import ClassVar

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import DataTable, RichLog, Static

from lazygitlab.infrastructure.logger import get_logger
from lazygitlab.models import CommentContext, CommentType, Discussion
from lazygitlab.services import CommentService, MRService
from lazygitlab.services.exceptions import LazyGitLabAPIError
from lazygitlab.tui.entities import ContentViewState, DiffViewMode
from lazygitlab.tui.messages import CommentPosted, ShowDiff, ShowOverview
from lazygitlab.tui.screens.comment_dialog import CommentDialog
from lazygitlab.tui.screens.error_dialog import ErrorDialog

_logger = get_logger(__name__)

# diff 行スタイル（Rich markup / style 文字列）
_DIFF_ADD_STYLE = "on #1a3a1a"
_DIFF_REM_STYLE = "on #3a1a1a"
_DIFF_HUNK_STYLE = "bold #6688cc"
_DIFF_GAP_STYLE = "dim italic"

# ±コンテキスト行数（デフォルト表示する変更行前後の行数）
_CONTEXT_LINES = 5


def _format_diff_line(line: str) -> str:
    """差分の1行を Rich マークアップでフォーマットする（テスト用に保持）。"""
    if line.startswith("@@"):
        return f"[{_DIFF_HUNK_STYLE}]{line}[/]"
    if line.startswith("+") and not line.startswith("+++"):
        escaped = line.replace("[", r"\[")
        return f"[{_DIFF_ADD_STYLE}]{escaped}[/]"
    if line.startswith("-") and not line.startswith("---"):
        escaped = line.replace("[", r"\[")
        return f"[{_DIFF_REM_STYLE}]{escaped}[/]"
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


def _parse_diff(diff_text: str) -> list[tuple[str, int | None, int | None, str]]:
    """unified diff を解析してタプルリストを返す。

    Returns:
        list of (line_type, old_no, new_no, text)
        line_type: "hunk" | "header" | "add" | "rem" | "ctx"
    """
    parsed: list[tuple[str, int | None, int | None, str]] = []
    old_no = new_no = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            m = re.search(r"-(\d+)(?:,\d+)? \+(\d+)(?:,\d+)?", line)
            if m:
                old_no = int(m.group(1)) - 1
                new_no = int(m.group(2)) - 1
            parsed.append(("hunk", None, None, line))
        elif line.startswith("---") or line.startswith("+++"):
            parsed.append(("header", None, None, line))
        elif line.startswith("+"):
            new_no += 1
            parsed.append(("add", None, new_no, line))
        elif line.startswith("-"):
            old_no += 1
            parsed.append(("rem", old_no, None, line))
        else:
            old_no += 1
            new_no += 1
            parsed.append(("ctx", old_no, new_no, line))
    return parsed


def _apply_context_filter(
    parsed: list[tuple[str, int | None, int | None, str]],
    context: int,
) -> list[tuple[str, int | None, int | None, str]]:
    """コンテキスト行を ±context 行に制限し、隠れた行を "gap" エントリに置換する。"""
    changes = {i for i, (t, *_) in enumerate(parsed) if t in ("add", "rem")}

    def _keep(i: int, t: str) -> bool:
        if t != "ctx":
            return True
        return any(abs(i - c) <= context for c in changes)

    result: list[tuple[str, int | None, int | None, str]] = []
    i = 0
    while i < len(parsed):
        t = parsed[i][0]
        if not _keep(i, t):
            gap = 0
            while i < len(parsed) and not _keep(i, parsed[i][0]):
                gap += 1
                i += 1
            result.append(("gap", None, None, f"··· {gap} lines hidden ···"))
        else:
            result.append(parsed[i])
            i += 1
    return result


def _wrap_text(text: str, width: int) -> str:
    """テキストを指定幅で折り返す（コード向け文字単位）。"""
    if len(text) <= width:
        return text
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


class ContentPanel(Widget):
    """右ペイン: Overview・差分をレンダリングするウィジェット。"""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("t", "toggle_diff_mode", "Toggle unified/side-by-side", priority=True),
        Binding("c", "add_comment", "Add Comment", priority=True),
        Binding("w", "toggle_wrap", "Wrap", priority=True),
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
        self._diff_row_lines: list[int | None] = []
        self._comment_lines: set[int] = set()
        self._editor_command: str = "vi"
        self._wrap_lines: bool = False

    def compose(self) -> ComposeResult:
        yield Static("Select an MR from the list.", id="empty-hint")
        yield RichLog(id="content-log", highlight=False, markup=True, wrap=False)
        yield DataTable(id="diff-table", cursor_type="row", show_header=True, zebra_stripes=False)
        with Horizontal(id="sbs-container"):
            yield DataTable(
                id="diff-table-left", cursor_type="row", show_header=True, zebra_stripes=False
            )
            yield DataTable(
                id="diff-table-right", cursor_type="row", show_header=True, zebra_stripes=False
            )

    def on_mount(self) -> None:
        self.query_one(RichLog).display = False
        table = self.query_one("#diff-table", DataTable)
        table.display = False
        self.query_one("#sbs-container").display = False

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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """選択行を更新し、SBS モードでは対向テーブルのカーソルを同期する。"""
        if self._view_state != ContentViewState.DIFF:
            return
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._diff_row_lines):
            line_no = self._diff_row_lines[row_idx]
            if line_no is not None:
                self._selected_line = line_no

        if self._diff_mode == DiffViewMode.SIDE_BY_SIDE:
            source = event.data_table
            try:
                left = self.query_one("#diff-table-left", DataTable)
                right = self.query_one("#diff-table-right", DataTable)
                other = right if source is left else left
                other.move_cursor(row=row_idx, animate=False)
            except Exception as e:
                _logger.debug(f"Failed to sync cursor in SBS mode: {e}")

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
            log.write(RichMarkdown(text))
            self._view_state = ContentViewState.OVERVIEW
            log.focus()
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load overview for !%d: %s", mr_iid, exc.message)
            self._view_state = ContentViewState.ERROR
            await self.app.push_screen(ErrorDialog(exc.message))
        finally:
            self.app.sub_title = ""

    async def _load_diff(self, mr_iid: int, file_path: str) -> None:
        self._view_state = ContentViewState.LOADING
        self.app.sub_title = f"Loading diff for {file_path}..."
        self._show_diff_table()
        table = self.query_one("#diff-table", DataTable)
        table.clear(columns=True)
        self._diff_row_lines = []
        self._selected_line = None
        try:
            file_diff, discussions = await _gather_two(
                self._mr_service.get_mr_diff(mr_iid, file_path),
                self._comment_service.get_discussions(mr_iid),
            )
            self._comment_lines = _get_comment_lines(discussions)
            self._render_diff(file_diff.diff, file_path)
            self._view_state = ContentViewState.DIFF
            if self._diff_mode == DiffViewMode.UNIFIED:
                table.focus()
            else:
                self.query_one("#diff-table-left", DataTable).focus()
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load diff for !%d %s: %s", mr_iid, file_path, exc.message)
            self._view_state = ContentViewState.ERROR
            await self.app.push_screen(ErrorDialog(exc.message))
        finally:
            self.app.sub_title = ""

    # --- 表示切替ヘルパー ---

    def _show_log(self) -> None:
        self.query_one("#empty-hint").display = False
        self.query_one(RichLog).display = True
        self.query_one("#diff-table", DataTable).display = False
        self.query_one("#sbs-container").display = False

    def _show_diff_table(self) -> None:
        self.query_one("#empty-hint").display = False
        self.query_one(RichLog).display = False
        if self._diff_mode == DiffViewMode.UNIFIED:
            self.query_one("#diff-table", DataTable).display = True
            self.query_one("#sbs-container").display = False
        else:
            self.query_one("#diff-table", DataTable).display = False
            self.query_one("#sbs-container").display = True

    # --- 差分レンダラー ---

    def _render_diff(self, diff_text: str, file_path: str) -> None:
        """差分テキストを DataTable にレンダリングする。"""
        table = self.query_one("#diff-table", DataTable)
        table.clear(columns=True)

        if self._diff_mode == DiffViewMode.UNIFIED:
            table.add_column("Old", key="old_no", width=5)
            table.add_column("New", key="new_no", width=5)
            table.add_column("Content", key="content")
            self._render_unified_table(table, diff_text)
        else:
            left = self.query_one("#diff-table-left", DataTable)
            right = self.query_one("#diff-table-right", DataTable)
            left.clear(columns=True)
            right.clear(columns=True)
            left.add_column("Old#", key="old_no", width=5)
            left.add_column("Old", key="old_content")
            right.add_column("New#", key="new_no", width=5)
            right.add_column("New", key="new_content")
            self._render_sbs_tables(left, right, diff_text)

    def _content_cell(self, text: str, style: str = "") -> Text:
        """折り返しモードに応じてコンテンツセル用 Text を返す。"""
        if self._wrap_lines:
            # パネル幅から行番号列2本(各5文字)+余白を引いた幅
            wrap_width = max(40, self.size.width - 15)
            text = _wrap_text(text, wrap_width)
            return Text(text, style=style)
        return Text(text, style=style, no_wrap=True)

    def _render_unified_table(self, table: DataTable, diff_text: str) -> None:
        """unified diff を DataTable に描画する（±コンテキスト行フィルタ付き）。"""
        parsed = _parse_diff(diff_text)
        rows = _apply_context_filter(parsed, _CONTEXT_LINES)
        row_idx = 0

        for t, old_n, new_n, text in rows:
            if t == "gap":
                table.add_row(
                    Text("···", style=_DIFF_GAP_STYLE),
                    Text("···", style=_DIFF_GAP_STYLE),
                    self._content_cell(text, _DIFF_GAP_STYLE),
                    key=f"gap_{row_idx}",
                )
                self._diff_row_lines.append(None)
            elif t == "hunk":
                table.add_row(
                    Text("", style=_DIFF_HUNK_STYLE),
                    Text("", style=_DIFF_HUNK_STYLE),
                    self._content_cell(text, _DIFF_HUNK_STYLE),
                    key=f"hunk_{row_idx}",
                )
                self._diff_row_lines.append(None)
            elif t == "header":
                table.add_row("", "", self._content_cell(text, "dim"), key=f"hdr_{row_idx}")
                self._diff_row_lines.append(None)
            elif t == "add":
                comment = " 💬" if new_n in self._comment_lines else ""
                table.add_row(
                    Text("", style=_DIFF_ADD_STYLE),
                    Text(str(new_n), style=_DIFF_ADD_STYLE),
                    self._content_cell(text + comment, _DIFF_ADD_STYLE),
                    key=f"add_{row_idx}",
                )
                self._diff_row_lines.append(new_n)
            elif t == "rem":
                table.add_row(
                    Text(str(old_n), style=_DIFF_REM_STYLE),
                    Text("", style=_DIFF_REM_STYLE),
                    self._content_cell(text, _DIFF_REM_STYLE),
                    key=f"rem_{row_idx}",
                )
                self._diff_row_lines.append(None)
            else:  # ctx
                comment = " 💬" if new_n in self._comment_lines else ""
                table.add_row(
                    str(old_n) if old_n is not None else "",
                    str(new_n) if new_n is not None else "",
                    self._content_cell(text + comment),
                    key=f"ctx_{row_idx}",
                )
                self._diff_row_lines.append(new_n)
            row_idx += 1

    def _render_sbs_tables(self, left: DataTable, right: DataTable, diff_text: str) -> None:
        """side-by-side の左右テーブルを同時に描画する。
        diff_text を1回だけ解析し、左右に同数の行を追加することで
        カーソル同期が正しく機能することを保証する。
        """
        parsed = _parse_diff(diff_text)
        rows = _apply_context_filter(parsed, _CONTEXT_LINES)
        row_idx = 0

        pending_rem: list[tuple[int | None, str]] = []
        pending_add: list[tuple[int | None, str]] = []

        def _flush() -> None:
            nonlocal row_idx
            if not pending_rem and not pending_add:
                return
            max_len = max(len(pending_rem), len(pending_add))
            for k in range(max_len):
                old_n2, old_t = pending_rem[k] if k < len(pending_rem) else (None, "")
                new_n2, new_t = pending_add[k] if k < len(pending_add) else (None, "")
                left.add_row(
                    Text(str(old_n2) if old_n2 else "", style=_DIFF_REM_STYLE if old_t else ""),
                    self._content_cell(old_t, _DIFF_REM_STYLE if old_t else ""),
                    key=f"sbs_l_{row_idx}",
                )
                right.add_row(
                    Text(str(new_n2) if new_n2 else "", style=_DIFF_ADD_STYLE if new_t else ""),
                    self._content_cell(new_t, _DIFF_ADD_STYLE if new_t else ""),
                    key=f"sbs_r_{row_idx}",
                )
                self._diff_row_lines.append(new_n2)
                row_idx += 1
            pending_rem.clear()
            pending_add.clear()

        for t, old_n, new_n, text in rows:
            if t == "rem":
                pending_rem.append((old_n, text[1:] if text.startswith("-") else text))
            elif t == "add":
                pending_add.append((new_n, text[1:] if text.startswith("+") else text))
            else:
                _flush()
                if t == "gap":
                    left.add_row(
                        Text("···", style=_DIFF_GAP_STYLE),
                        self._content_cell(text, _DIFF_GAP_STYLE),
                        key=f"gap_l_{row_idx}",
                    )
                    right.add_row(
                        Text("···", style=_DIFF_GAP_STYLE),
                        self._content_cell(text, _DIFF_GAP_STYLE),
                        key=f"gap_r_{row_idx}",
                    )
                    self._diff_row_lines.append(None)
                elif t == "hunk":
                    left.add_row(
                        Text("", style=_DIFF_HUNK_STYLE),
                        self._content_cell(text, _DIFF_HUNK_STYLE),
                        key=f"hunk_l_{row_idx}",
                    )
                    right.add_row(
                        Text("", style=_DIFF_HUNK_STYLE),
                        self._content_cell(text, _DIFF_HUNK_STYLE),
                        key=f"hunk_r_{row_idx}",
                    )
                    self._diff_row_lines.append(None)
                elif t == "header":
                    left.add_row("", self._content_cell(text, "dim"), key=f"hdr_l_{row_idx}")
                    right.add_row("", self._content_cell(text, "dim"), key=f"hdr_r_{row_idx}")
                    self._diff_row_lines.append(None)
                else:  # ctx
                    ctx_text = text[1:] if text.startswith(" ") else text
                    left.add_row(
                        str(old_n) if old_n is not None else "",
                        self._content_cell(ctx_text),
                        key=f"ctx_l_{row_idx}",
                    )
                    right.add_row(
                        str(new_n) if new_n is not None else "",
                        self._content_cell(ctx_text),
                        key=f"ctx_r_{row_idx}",
                    )
                    self._diff_row_lines.append(new_n)
                row_idx += 1

        _flush()

    # --- クエリ ---

    def get_selected_line(self) -> tuple[str, int] | None:
        """現在選択中の (file_path, line_number) を返す。行未選択時は行1を使用。"""
        if self._view_state == ContentViewState.DIFF and self._current_file_path is not None:
            return (self._current_file_path, self._selected_line or 1)
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

    def action_toggle_wrap(self) -> None:
        """差分表示の折り返しモードを切り替える。"""
        if self._view_state != ContentViewState.DIFF:
            return
        self._wrap_lines = not self._wrap_lines
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
        self._diff_row_lines = []
        log = self.query_one(RichLog)
        log.clear()
        log.display = False
        table = self.query_one("#diff-table", DataTable)
        table.clear(columns=True)
        table.display = False
        self.query_one("#diff-table-left", DataTable).clear(columns=True)
        self.query_one("#diff-table-right", DataTable).clear(columns=True)
        self.query_one("#sbs-container").display = False
        self.query_one("#empty-hint").display = True


async def _gather_two(coro1, coro2):
    """2つのコルーチンを並行実行して結果のタプルを返す。"""
    import asyncio

    result1, result2 = await asyncio.gather(coro1, coro2)
    return result1, result2
