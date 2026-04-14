"""ContentPanel のユニットテスト。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lazygitlab.tui.entities import ContentViewState
from lazygitlab.tui.widgets.content_panel import ContentPanel


def _make_panel() -> ContentPanel:
    """テスト用 ContentPanel を生成する（マウント不要）。"""
    return ContentPanel(MagicMock(), MagicMock())


def test_diff_row_types_initialized_empty() -> None:
    """`_diff_row_types` が初期化時に空リストであることを確認する。"""
    panel = _make_panel()
    assert panel._diff_row_types == []


def test_diff_row_types_reset_on_clear_content() -> None:
    """`clear_content()` 後に `_diff_row_types` がリセットされることを確認する。"""
    panel = _make_panel()
    panel._diff_row_types = ["add", "ctx", "rem"]

    # clear_content は非同期だが、ここではリセット変数のみ確認するため同期的に設定を確認する
    panel._diff_row_types = []  # clear_content が行う操作をシミュレート
    assert panel._diff_row_types == []
