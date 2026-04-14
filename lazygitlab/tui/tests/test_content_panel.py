"""ContentPanel のユニットテスト。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lazygitlab.tui.widgets.content_panel import ContentPanel


def _make_panel() -> ContentPanel:
    """テスト用 ContentPanel を生成する（マウント不要）。"""
    return ContentPanel(MagicMock(), MagicMock())


def test_diff_row_types_initialized_empty() -> None:
    """`_diff_row_types` が初期化時に空リストであることを確認する。"""
    panel = _make_panel()
    assert panel._diff_row_types == []


@pytest.mark.asyncio
async def test_diff_row_types_reset_on_clear_content() -> None:
    """`clear_content()` 後に `_diff_row_types` がリセットされることを確認する。"""
    panel = _make_panel()
    panel._diff_row_types = ["add", "ctx", "rem"]

    # clear_content は Textual の DOM にアクセスするためモックする
    mock_log = MagicMock()
    mock_table = MagicMock()

    def _query_one(selector, *args):
        from textual.widgets import RichLog

        if selector is RichLog or selector == RichLog:
            return mock_log
        return mock_table

    with patch.object(panel, "query_one", side_effect=_query_one):
        await panel.clear_content()

    assert panel._diff_row_types == []
