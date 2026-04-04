"""GitLab API サービス層のカスタム例外クラス。"""

from __future__ import annotations


class LazyGitLabAPIError(Exception):
    """API層の基底エラー。ユーザー向けメッセージを保持する。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class GitLabAuthError(LazyGitLabAPIError):
    """GitLab認証失敗(401)。"""


class GitLabConnectionError(LazyGitLabAPIError):
    """GitLabサーバーへの接続失敗またはタイムアウト。"""


class GitLabProjectNotFoundError(LazyGitLabAPIError):
    """指定されたGitLabプロジェクトが見つからない(404)。"""


class GitLabAccessDeniedError(LazyGitLabAPIError):
    """GitLabリソースへのアクセス権限がない(403)。"""


class MRNotFoundError(LazyGitLabAPIError):
    """指定されたMRが見つからない。"""


class FileNotFoundInMRError(LazyGitLabAPIError):
    """MR内に指定されたファイルが見つからない。"""


class DiscussionNotFoundError(LazyGitLabAPIError):
    """指定されたディスカッションが見つからない。"""


class EmptyCommentError(LazyGitLabAPIError):
    """コメント本文が空または空白のみ。"""
