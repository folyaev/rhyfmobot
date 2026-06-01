import argparse
import os
from datetime import datetime
from pathlib import Path

from database import RhymesRepository


def parse_args():
    default_source = Path(os.getenv('DB_PATH', 'data/rhymes.db'))
    default_target = Path('data/backups') / f"rhymes-{datetime.now():%Y%m%d-%H%M%S}.db"
    parser = argparse.ArgumentParser(description='Create a consistent SQLite backup.')
    parser.add_argument('--source', type=Path, default=default_source)
    parser.add_argument('--target', type=Path, default=default_target)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.source.exists():
        raise SystemExit(f'Database does not exist: {args.source}')

    RhymesRepository(args.source).backup(args.target)
    print(f'Backup created: {args.target}')


if __name__ == '__main__':
    main()
