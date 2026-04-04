"""MRListPanel — 左ペインのMR一覧ツリーウィジェット。"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.widgets import Tree
from textual.widgets._tree import TreeNode
from textual.widget import Widget

from lazygitlab.infrastructure.logger import get_logger
from lazygitlab.services import MRService
from lazygitlab.services.exceptions import LazyGitLabAPIError
from lazygitlab.services.types import MRCategory
from lazygitlab.tui.entities import (
    CATEGORY_LABELS,
    ContentViewState,
    TreeNodeData,
    TreeNodeType,
    get_file_change_label,
)
from lazygitlab.tui.messages import ShowDiff, ShowOverview
from lazygitlab.tui.screens.error_dialog import ErrorDialog

_logger = get_logger(__name__)


class MRListPanel(Widget):
    """左ペイン: MRをカテゴリ別ツリーで表示するウィジェット。"""

    DEFAULT_CSS = """
    MRListPanel {
        width: 30%;
        height: 100%;
    }
    """

    def __init__(self, mr_service: MRService) -> None:
        super().__init__()
        self._mr_service = mr_service
        self._category_pages: dict[MRCategory, int] = {cat: 1 for cat in MRCategory}
        self._selected_mr_iid: int | None = None
        self._expanded_mrs: set[int] = set()
        # カテゴリノードへの参照を保持
        self._category_nodes: dict[MRCategory, TreeNode[TreeNodeData]] = {}

    def compose(self) -> ComposeResult:
        yield Tree("Merge Requests", id="mr-tree")

    def on_mount(self) -> None:
        self.run_worker(self._load_all_categories(), exclusive=True)

    async def _load_all_categories(self) -> None:
        """4カテゴリを並行取得してツリーを構築する。"""
        tree = self.query_one(Tree)
        tree.root.expand()

        self.app.sub_title = "Loading MR list..."
        try:
            results = await asyncio.gather(
                self._mr_service.get_assigned_to_me(page=1),
                self._mr_service.get_created_by_me(page=1),
                self._mr_service.get_unassigned(page=1),
                self._mr_service.get_assigned_to_others(page=1),
                return_exceptions=True,
            )
        finally:
            self.app.sub_title = ""

        categories = [
            MRCategory.ASSIGNED_TO_ME,
            MRCategory.CREATED_BY_ME,
            MRCategory.UNASSIGNED,
            MRCategory.ASSIGNED_TO_OTHERS,
        ]

        for category, result in zip(categories, results):
            if isinstance(result, Exception):
                _logger.error("Failed to load %s: %s", category, result)
                label = f"{CATEGORY_LABELS[category]} (error)"
                node = tree.root.add(
                    label,
                    data=TreeNodeData(node_type=TreeNodeType.CATEGORY, category=category),
                    expand=False,
                )
                self._category_nodes[category] = node
                continue

            paginated = result
            count = len(paginated.items)
            label = f"{CATEGORY_LABELS[category]} ({count})"
            cat_node = tree.root.add(
                label,
                data=TreeNodeData(node_type=TreeNodeType.CATEGORY, category=category),
                expand=True,
            )
            self._category_nodes[category] = cat_node

            if count == 0:
                cat_node.add_leaf(
                    "(empty)",
                    data=TreeNodeData(node_type=TreeNodeType.CATEGORY, category=category),
                )
            else:
                for mr in paginated.items:
                    cat_node.add_leaf(
                        f"!{mr.iid} {mr.title}",
                        data=TreeNodeData(node_type=TreeNodeType.MR, mr_iid=mr.iid),
                    )
                if paginated.has_next_page and paginated.next_page is not None:
                    self._category_pages[category] = paginated.next_page
                    cat_node.add_leaf(
                        "Load more...",
                        data=TreeNodeData(
                            node_type=TreeNodeType.LOAD_MORE,
                            category=category,
                            next_page=paginated.next_page,
                        ),
                    )

    async def _expand_mr(self, node: TreeNode[TreeNodeData], mr_iid: int) -> None:
        """MRノードを展開してファイル一覧を表示する。"""
        self.app.sub_title = f"Loading MR !{mr_iid}..."
        try:
            changes = await self._mr_service.get_mr_changes(mr_iid)
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load MR changes for !%d: %s", mr_iid, exc.message)
            await self.app.push_screen(ErrorDialog(exc.message))
            return
        finally:
            self.app.sub_title = ""

        self._expanded_mrs.add(mr_iid)

        # Overview ノード
        node.add_leaf(
            "Overview",
            data=TreeNodeData(node_type=TreeNodeType.OVERVIEW, mr_iid=mr_iid),
        )
        # ファイルノード
        for change in changes:
            label = get_file_change_label(
                old_path=change.old_path,
                new_path=change.new_path,
                new_file=change.new_file,
                deleted_file=change.deleted_file,
                renamed_file=change.renamed_file,
            )
            node.add_leaf(
                label,
                data=TreeNodeData(
                    node_type=TreeNodeType.FILE,
                    mr_iid=mr_iid,
                    file_path=change.new_path,
                ),
            )
        node.expand()

    async def _load_more(self, node: TreeNode[TreeNodeData]) -> None:
        """追加ページを取得してノードを追加する。"""
        data = node.data
        if data is None or data.category is None or data.next_page is None:
            return

        category = data.category
        page = data.next_page
        self.app.sub_title = f"Loading more {CATEGORY_LABELS[category]}..."

        try:
            result = await self._mr_service._get_mr_list_by_category(category, page=page)
        except LazyGitLabAPIError as exc:
            _logger.error("Failed to load more MRs: %s", exc.message)
            await self.app.push_screen(ErrorDialog(exc.message))
            return
        except AttributeError:
            # _get_mr_list_by_category が存在しない場合のフォールバック
            _logger.warning("Category load more not available for %s", category)
            return
        finally:
            self.app.sub_title = ""

        parent = node.parent
        if parent is None:
            return

        # "Load more..." ノードを削除してMRを追加
        node.remove()

        for mr in result.items:
            parent.add_leaf(
                f"!{mr.iid} {mr.title}",
                data=TreeNodeData(node_type=TreeNodeType.MR, mr_iid=mr.iid),
            )

        if result.has_next_page and result.next_page is not None:
            self._category_pages[category] = result.next_page
            parent.add_leaf(
                "Load more...",
                data=TreeNodeData(
                    node_type=TreeNodeType.LOAD_MORE,
                    category=category,
                    next_page=result.next_page,
                ),
            )

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """ツリーノード選択イベントを処理する。"""
        node = event.node
        data: TreeNodeData | None = node.data
        if data is None:
            return

        if data.node_type == TreeNodeType.CATEGORY:
            return

        if data.node_type == TreeNodeType.MR:
            mr_iid = data.mr_iid
            if mr_iid is None:
                return
            if mr_iid in self._expanded_mrs:
                node.toggle()
            else:
                self.run_worker(self._expand_mr(node, mr_iid), exclusive=False)
            return

        if data.node_type == TreeNodeType.OVERVIEW:
            if data.mr_iid is not None:
                self.post_message(ShowOverview(data.mr_iid))
            return

        if data.node_type == TreeNodeType.FILE:
            if data.mr_iid is not None and data.file_path is not None:
                self.post_message(ShowDiff(data.mr_iid, data.file_path))
            return

        if data.node_type == TreeNodeType.LOAD_MORE:
            self.run_worker(self._load_more(node), exclusive=False)

    async def refresh_list(self) -> None:
        """MR一覧を再取得する（リフレッシュ時）。"""
        tree = self.query_one(Tree)
        tree.root.remove_children()
        self._category_nodes.clear()
        self._expanded_mrs.clear()
        self._category_pages = {cat: 1 for cat in MRCategory}
        await self._load_all_categories()
