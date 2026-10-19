#!/usr/bin/env python3
"""Seed invitation codes into the exam SQLite database without overwriting usage."""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("codes", type=Path)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    codes = [line.strip().upper() for line in args.codes.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if len(codes) != len(set(codes)):
        raise SystemExit("邀请码文件存在重复项")
    connection = sqlite3.connect(args.database)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS invitation_codes (
            code TEXT PRIMARY KEY, created_at INTEGER NOT NULL, used_by INTEGER UNIQUE, used_at INTEGER
        )"""
    )
    now = int(time.time())
    before = connection.total_changes
    connection.executemany(
        "INSERT OR IGNORE INTO invitation_codes(code, created_at, used_by, used_at) VALUES (?, ?, NULL, NULL)",
        [(code, now) for code in codes],
    )
    inserted = connection.total_changes - before
    connection.commit()
    available = connection.execute("SELECT COUNT(*) FROM invitation_codes WHERE used_by IS NULL").fetchone()[0]
    connection.close()
    print(f"seeded={inserted} available={available} supplied={len(codes)}")


if __name__ == "__main__":
    main()

