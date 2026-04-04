"""lazygitlab アプリケーションのエントリーポイント。"""

from __future__ import annotations

import argparse
import sys

from lazygitlab.infrastructure.logger import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lazygitlab",
        description="A TUI application for browsing and commenting on GitLab merge requests",
    )
    parser.add_argument(
        "mr_id",
        nargs="?",
        type=int,
        default=None,
        help="Merge request IID to open directly on startup",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from lazygitlab.infrastructure.config import ConfigManager

        config_manager = ConfigManager()
        config = config_manager.load()

        setup_logging(config.log_level)
        logger = get_logger(__name__)
        logger.info("lazygitlab starting")

        # TUIアプリケーションのエントリーポイント（UNIT-03で実装）
        # プレースホルダー: アプリのインポートと起動
        from lazygitlab.app import LazyGitLabApp

        app = LazyGitLabApp(config=config, initial_mr_id=args.mr_id)
        app.run()

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(0)
    except Exception as exc:
        logger_fallback = get_logger(__name__)
        logger_fallback.exception("Unhandled exception during startup")
        # SECURITY-09: ユーザーには汎用的なメッセージのみ表示する
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
