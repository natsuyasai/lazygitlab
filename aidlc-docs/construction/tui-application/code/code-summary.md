# UNIT-03: TUI Application コードサマリー

## 概要

UNIT-03（TUI Application）のコード生成結果を記録する。Textualフレームワークを使用したTUIアプリケーションの全コンポーネントを実装した。

---

## 生成ファイル一覧

### パッケージ初期化

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/__init__.py` | TUIパッケージ。LazyGitLabApp を公開 |
| `lazygitlab/tui/widgets/__init__.py` | ウィジェットパッケージ。MRListPanel, ContentPanel を公開 |
| `lazygitlab/tui/screens/__init__.py` | スクリーンパッケージ。CommentDialog, ErrorDialog, HelpScreen を公開 |
| `lazygitlab/tui/tests/__init__.py` | テストパッケージ |

### ドメインエンティティ・メッセージ

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/entities.py` | DiffViewMode, TreeNodeType, TreeNodeData, ContentViewState, CATEGORY_LABELS, get_file_change_label |
| `lazygitlab/tui/messages.py` | ShowOverview, ShowDiff, CommentPosted（Textual Messages） |

### スタイル

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/styles.tcss` | Textual CSS（レイアウト・差分カラー・モーダルサイズ） |

### モーダルスクリーン

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/screens/error_dialog.py` | ErrorDialog — エラーメッセージ表示。Enter/Escapeで閉じる |
| `lazygitlab/tui/screens/help_screen.py` | HelpScreen — キーバインド一覧。DataTableで表示。Escapeで閉じる |
| `lazygitlab/tui/screens/comment_dialog.py` | CommentDialog — INLINE/NOTE/REPLY対応。外部エディタ連携（Ctrl+E）、Ctrl+S送信 |

### ウィジェット

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/widgets/mr_list_panel.py` | MRListPanel — 4カテゴリの並行取得、MRツリー展開（ファイル一覧+Overview）、Load moreページネーション |
| `lazygitlab/tui/widgets/content_panel.py` | ContentPanel — Overview/差分表示、Pygmentsハイライト、unified/side-by-sideトグル、コメントマーカー |

### メインアプリ

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/app.py` | LazyGitLabApp — GitLab接続、ウィジェット初期化、グローバルキーバインド（q/?/r/e/[）、外部エディタ起動 |

### エントリポイント（更新）

| ファイル | 説明 |
|---|---|
| `lazygitlab/__main__.py` | インポートパスを `lazygitlab.tui.app.LazyGitLabApp` に更新 |

### テスト

| ファイル | 説明 |
|---|---|
| `lazygitlab/tui/tests/test_entities.py` | エンティティ・ロジック単体テスト（DiffViewMode, TreeNodeData, ContentViewState, ラベル生成, 差分フォーマット, コメント行取得） |
| `lazygitlab/tui/tests/test_pilot.py` | Textual Pilotテスト（アプリ終了, ヘルプ表示, サイドバートグル, 接続失敗時ErrorDialog, ErrorDialogのOK操作） |

---

## アプリケーション起動フロー

```
lazygitlab [mr_id]
    |
    v
__main__.py: ConfigManager.load() → setup_logging() → LazyGitLabApp(config, mr_id).run()
    |
    v
LazyGitLabApp.on_mount()
    1. GitRepoDetector.get_project_info() → project_path
    2. GitLabClient(config).connect()
    3. MRService(client, project_path).load()
    4. CommentService(client, project_path).load()
    5. MRListPanel(mr_service) + ContentPanel(mr_service, comment_service) をマウント
    6. initial_mr_id があれば MRListPanel.expand_mr() を呼び出す
    |
    v
MRListPanel.on_mount()
    asyncio.gather で4カテゴリ並行取得 → ツリーノード構築
    |
    v
ユーザー操作 → イベント処理 → ShowOverview / ShowDiff メッセージ
    |
    v
ContentPanel.on_show_overview() / on_show_diff()
    API取得 → Pygmentsハイライト → RichLogレンダリング
```

---

## テストカバレッジ概要

| 対象 | テスト種別 | カバレッジ目標 |
|---|---|---|
| entities.py | 単体テスト | 100% |
| messages.py | 単体テスト（使用箇所から間接的に） | — |
| content_panel.py（ロジック関数） | 単体テスト | 100% |
| app.py（基本フロー） | Textual Pilot | 基本ケース |
| screens/error_dialog.py | Textual Pilot | 基本ケース |
| screens/help_screen.py | Textual Pilot | 基本ケース |

---

## UNIT-01/UNIT-02 依存関係

```
UNIT-01 依存:
  AppConfig        → LazyGitLabApp（設定値）
  ConfigManager    → __main__.py（設定読み込み）
  GitRepoDetector  → LazyGitLabApp（プロジェクトパス検出）
  get_logger       → 全コンポーネント

UNIT-02 依存:
  GitLabClient     → LazyGitLabApp（接続管理）
  MRService        → MRListPanel, ContentPanel
  CommentService   → ContentPanel, CommentDialog
  PaginatedResult  → MRListPanel（ページネーション）
  MRCategory       → MRListPanel, entities.py
  LazyGitLabAPIError → 全コンポーネント（エラーハンドリング）
```
