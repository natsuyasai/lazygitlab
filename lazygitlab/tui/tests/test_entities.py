"""TUI エンティティおよびロジック単体テスト。"""

from __future__ import annotations

from lazygitlab.models import Discussion, Note, NotePosition
from lazygitlab.services.types import MRCategory
from lazygitlab.tui.entities import (
    CATEGORY_LABELS,
    ContentViewState,
    DiffViewMode,
    TreeNodeData,
    TreeNodeType,
    get_file_change_label,
)
from lazygitlab.tui.widgets.content_panel import _format_diff_line, _get_comment_lines


class TestDiffViewMode:
    def test_all_values(self) -> None:
        assert DiffViewMode.UNIFIED.value == "unified"
        assert DiffViewMode.SIDE_BY_SIDE.value == "side_by_side"

    def test_toggle_logic(self) -> None:
        mode = DiffViewMode.UNIFIED
        toggled = (
            DiffViewMode.SIDE_BY_SIDE if mode == DiffViewMode.UNIFIED else DiffViewMode.UNIFIED
        )
        assert toggled == DiffViewMode.SIDE_BY_SIDE

    def test_toggle_back(self) -> None:
        mode = DiffViewMode.SIDE_BY_SIDE
        toggled = (
            DiffViewMode.SIDE_BY_SIDE if mode == DiffViewMode.UNIFIED else DiffViewMode.UNIFIED
        )
        assert toggled == DiffViewMode.UNIFIED


class TestTreeNodeType:
    def test_all_values(self) -> None:
        assert TreeNodeType.CATEGORY.value == "category"
        assert TreeNodeType.MR.value == "mr"
        assert TreeNodeType.OVERVIEW.value == "overview"
        assert TreeNodeType.FILE.value == "file"
        assert TreeNodeType.LOAD_MORE.value == "load_more"


class TestTreeNodeData:
    def test_defaults(self) -> None:
        data = TreeNodeData(node_type=TreeNodeType.CATEGORY)
        assert data.mr_iid is None
        assert data.file_path is None
        assert data.category is None
        assert data.next_page is None

    def test_mr_node(self) -> None:
        data = TreeNodeData(node_type=TreeNodeType.MR, mr_iid=42)
        assert data.node_type == TreeNodeType.MR
        assert data.mr_iid == 42

    def test_file_node(self) -> None:
        data = TreeNodeData(node_type=TreeNodeType.FILE, mr_iid=1, file_path="src/main.py")
        assert data.file_path == "src/main.py"

    def test_load_more_node(self) -> None:
        data = TreeNodeData(
            node_type=TreeNodeType.LOAD_MORE,
            category=MRCategory.ASSIGNED_TO_ME,
            next_page=2,
        )
        assert data.category == MRCategory.ASSIGNED_TO_ME
        assert data.next_page == 2


class TestContentViewState:
    def test_all_values(self) -> None:
        assert ContentViewState.EMPTY.value == "empty"
        assert ContentViewState.OVERVIEW.value == "overview"
        assert ContentViewState.DIFF.value == "diff"
        assert ContentViewState.LOADING.value == "loading"
        assert ContentViewState.ERROR.value == "error"


class TestCategoryLabels:
    def test_all_categories_have_labels(self) -> None:
        for cat in MRCategory:
            assert cat in CATEGORY_LABELS
            assert len(CATEGORY_LABELS[cat]) > 0


class TestGetFileChangeLabel:
    def test_new_file(self) -> None:
        label = get_file_change_label("", "src/new.py", True, False, False)
        assert label.startswith("+")
        assert "src/new.py" in label

    def test_deleted_file(self) -> None:
        label = get_file_change_label("src/old.py", "", False, True, False)
        assert label.startswith("-")
        assert "src/old.py" in label

    def test_renamed_file(self) -> None:
        label = get_file_change_label("src/old.py", "src/new.py", False, False, True)
        assert "→" in label
        assert "src/old.py" in label
        assert "src/new.py" in label

    def test_modified_file(self) -> None:
        label = get_file_change_label("src/file.py", "src/file.py", False, False, False)
        assert "src/file.py" in label


class TestFormatDiffLine:
    def test_add_line(self) -> None:
        result = _format_diff_line("+added line")
        assert "1a3a1a" in result  # 追加行の背景色

    def test_remove_line(self) -> None:
        result = _format_diff_line("-removed line")
        assert "3a1a1a" in result  # 削除行の背景色

    def test_hunk_header(self) -> None:
        result = _format_diff_line("@@ -1,5 +1,7 @@")
        assert "6688cc" in result  # ハンクヘッダの色

    def test_context_line(self) -> None:
        result = _format_diff_line(" context line")
        assert "context line" in result

    def test_escapes_markup(self) -> None:
        result = _format_diff_line("+line with [brackets]")
        # Rich マークアップのブラケットがエスケープされていること
        assert r"\[" in result


class TestGetCommentLines:
    def test_empty_discussions(self) -> None:
        result = _get_comment_lines([])
        assert result == set()

    def test_inline_comment_lines(self) -> None:
        note = Note(
            id=1,
            author="user",
            body="comment",
            created_at="2026-01-01",
            position=NotePosition(file_path="file.py", new_line=10),
        )
        disc = Discussion(id="abc", notes=[note])
        result = _get_comment_lines([disc])
        assert 10 in result

    def test_old_line_comment(self) -> None:
        note = Note(
            id=2,
            author="user",
            body="comment on old line",
            created_at="2026-01-01",
            position=NotePosition(file_path="file.py", old_line=5),
        )
        disc = Discussion(id="def", notes=[note])
        result = _get_comment_lines([disc])
        assert 5 in result

    def test_no_position_note(self) -> None:
        note = Note(
            id=3,
            author="user",
            body="general comment",
            created_at="2026-01-01",
            position=None,
        )
        disc = Discussion(id="ghi", notes=[note])
        result = _get_comment_lines([disc])
        assert result == set()


class TestWrapText:
    def test_short_line_unchanged(self) -> None:
        from lazygitlab.tui.widgets.content_panel import _wrap_text

        assert _wrap_text("hello", 20) == "hello"

    def test_exact_width_unchanged(self) -> None:
        from lazygitlab.tui.widgets.content_panel import _wrap_text

        assert _wrap_text("a" * 20, 20) == "a" * 20

    def test_long_line_wraps(self) -> None:
        from lazygitlab.tui.widgets.content_panel import _wrap_text

        result = _wrap_text("a" * 50, 20)
        lines = result.split("\n")
        assert len(lines) == 3
        assert all(len(line) <= 20 for line in lines)

    def test_empty_string(self) -> None:
        from lazygitlab.tui.widgets.content_panel import _wrap_text

        assert _wrap_text("", 20) == ""


class TestSBSCursorSync:
    """SBS カーソル同期ロジックのテスト（純関数）。"""

    def test_diff_row_lines_populated_after_left_render(self) -> None:
        """_parse_diff と _apply_context_filter の組み合わせが SBS に必要な行データを提供できる。"""
        from lazygitlab.tui.widgets.content_panel import _apply_context_filter, _parse_diff

        diff = "@@ -1,2 +1,2 @@\n context\n-old\n+new\n"
        parsed = _parse_diff(diff)
        rows = _apply_context_filter(parsed, 5)

        # rem と add が1行ずつある
        types = [t for t, *_ in rows]
        assert types.count("rem") == 1
        assert types.count("add") == 1
        # ctx 行がある
        assert "ctx" in types


class TestSBSRendering:
    """side-by-side diff の行数対称性テスト。"""

    SAMPLE_DIFF = """\
@@ -1,3 +1,3 @@
 context
-old line
+new line
 context2
"""

    def test_parse_diff_has_expected_rows(self) -> None:
        from lazygitlab.tui.widgets.content_panel import _apply_context_filter, _parse_diff

        parsed = _parse_diff(self.SAMPLE_DIFF)
        rows = _apply_context_filter(parsed, 5)
        types = [t for t, *_ in rows]
        assert "add" in types
        assert "rem" in types
        assert "ctx" in types

    def test_sbs_pending_flush_balances_rows(self) -> None:
        """rem と add のペア数が一致する場合、左右の行数が等しい。"""
        from lazygitlab.tui.widgets.content_panel import _apply_context_filter, _parse_diff

        parsed = _parse_diff(self.SAMPLE_DIFF)
        rows = _apply_context_filter(parsed, 5)

        pending_rem: list = []
        pending_add: list = []
        left_rows: list = []
        right_rows: list = []

        def flush():
            max_len = max(len(pending_rem), len(pending_add), 1)
            for k in range(max_len if (pending_rem or pending_add) else 0):
                left_rows.append(pending_rem[k] if k < len(pending_rem) else None)
                right_rows.append(pending_add[k] if k < len(pending_add) else None)
            pending_rem.clear()
            pending_add.clear()

        for t, old_n, new_n, text in rows:
            if t == "rem":
                pending_rem.append((old_n, text))
            elif t == "add":
                pending_add.append((new_n, text))
            else:
                flush()
                left_rows.append((old_n, text))
                right_rows.append((new_n, text))
        flush()

        assert len(left_rows) == len(right_rows)


class TestOverflowCommentMarkers:
    """表示範囲外コメントの overflow マーカー割り当てテスト。"""

    def _make_panel(self, comment_lines: set[int]):
        """ContentPanel の _compute_overflow_comment_markers だけ使えるスタブを作る。"""
        from types import SimpleNamespace

        from lazygitlab.tui.widgets.content_panel import ContentPanel

        # インスタンスを作らずにメソッドだけ借用する
        stub = SimpleNamespace(_comment_lines=comment_lines)
        stub._compute_overflow_comment_markers = (
            ContentPanel._compute_overflow_comment_markers.__get__(stub)
        )
        return stub

    def test_no_comments_returns_empty(self) -> None:
        """コメントがない場合は空集合を返す。"""
        panel = self._make_panel(set())
        rows = [("ctx", 1, 1, " line")]
        assert panel._compute_overflow_comment_markers(rows) == set()

    def test_visible_comment_not_overflow(self) -> None:
        """diff に表示されているコメント行はオーバーフローにならない。"""
        panel = self._make_panel({1})
        rows = [("ctx", 1, 1, " line")]
        assert panel._compute_overflow_comment_markers(rows) == set()

    def test_single_overflow_maps_to_last_row(self) -> None:
        """表示範囲外のコメント1件が最後のコード行に割り当てられる。"""
        panel = self._make_panel({999})  # 999行目はdiffに存在しない
        rows = [
            ("ctx", 1, 1, " line1"),
            ("ctx", 2, 2, " line2"),
            ("add", None, 3, "+line3"),
        ]
        result = panel._compute_overflow_comment_markers(rows)
        # rows インデックス 2 (最後のコード行) が選ばれる
        assert result == {2}

    def test_multiple_overflows_stack_upward(self) -> None:
        """複数のオーバーフローコメントが末尾から逆順に割り当てられる。"""
        panel = self._make_panel({100, 200, 300})  # すべて範囲外
        rows = [
            ("ctx", 1, 1, " a"),
            ("ctx", 2, 2, " b"),
            ("ctx", 3, 3, " c"),
            ("add", None, 4, "+d"),
        ]
        result = panel._compute_overflow_comment_markers(rows)
        # 3件のオーバーフロー → 末尾3行 (インデックス 1, 2, 3) が選ばれる
        assert result == {1, 2, 3}

    def test_overflow_count_capped_by_visible_rows(self) -> None:
        """オーバーフロー件数が表示行数を超えても上限はコード行数まで。"""
        panel = self._make_panel({100, 200, 300, 400, 500})  # 5件
        rows = [
            ("ctx", 1, 1, " a"),
            ("ctx", 2, 2, " b"),
        ]
        result = panel._compute_overflow_comment_markers(rows)
        # コード行は2行しかないので最大2件
        assert result == {0, 1}

    def test_rem_row_visible_line_counted(self) -> None:
        """rem 行の old_n が visible_lines に含まれていれば overflow にならない。"""
        panel = self._make_panel({5})
        rows = [("rem", 5, None, "-line")]
        assert panel._compute_overflow_comment_markers(rows) == set()

    def test_hunk_and_gap_rows_not_code_rows(self) -> None:
        """hunk/gap 行はコード行としてカウントされない。"""
        panel = self._make_panel({999})
        rows = [
            ("hunk", None, None, "@@ -1,1 +1,1 @@"),
            ("gap", 1, 10, "..."),
            ("ctx", 1, 1, " line"),
        ]
        result = panel._compute_overflow_comment_markers(rows)
        # コード行はインデックス2のctxのみ
        assert result == {2}
