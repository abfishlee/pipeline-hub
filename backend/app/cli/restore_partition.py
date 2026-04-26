"""Phase 4.2.7 — partition archive 복원 CLI.

사용법:
    cd backend && uv run python -m app.cli.restore_partition --archive-id 42

옵션:
    --target-table  schema.table  (생략 시 `<schema>.<part>_restored`)
    --restored-by   user_id

ctl.partition_archive_log.status 가 ARCHIVED/DROPPED/COPIED 인 row 만 복원 가능.
"""

from __future__ import annotations

import argparse
import sys

from app.db.sync_session import get_sync_sessionmaker
from app.domain.partition_archive import restore_partition
from app.integrations.object_storage import get_object_storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore archived partition from Object Storage.")
    parser.add_argument("--archive-id", type=int, required=True)
    parser.add_argument(
        "--target-table",
        default=None,
        help="복원할 테이블 (생략 시 <schema>.<partition>_restored).",
    )
    parser.add_argument("--restored-by", type=int, default=None)
    args = parser.parse_args(argv)

    sm = get_sync_sessionmaker()
    storage = get_object_storage()
    with sm() as session:
        try:
            target = restore_partition(
                session,
                archive_id=args.archive_id,
                object_storage=storage,
                target_table=args.target_table,
                restored_by=args.restored_by,
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    print(f"restored to: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
