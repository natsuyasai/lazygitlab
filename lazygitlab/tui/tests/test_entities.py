"""TUI エンティティおよびロジック単体テスト。"""

from __future__ import annotations

import pytest

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
from lazygitlab.models import Discussion, Note, NotePosition


class TestDiffViewMode:
    def test_all_values(self) -> None:
        assert DiffViewMode.UNIFIED.value == "unified"
        assert DiffViewMode.SIDE_BY_SIDE.value == "side_by_side"

    def test_toggle_logic(self) -> None:
        mode = DiffViewMode.UNIFIED
        toggled = DiffViewMode.SIDE_BY_SIDE if mode == DiffViewMode.UNIFIED else DiffViewMode.UNIFIED
        assert toggled == DiffViewMode.SIDE_BY_SIDE

    def test_toggle_back(self) -> None:
        mode = DiffViewMode.SIDE_BY_SIDE
        toggled = DiffViewMode.SIDE_BY_SIDE if mode == DiffViewMode.UNIFIED else DiffViewMode.UNIFIED
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
