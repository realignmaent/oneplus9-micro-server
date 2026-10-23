#!/usr/bin/env python3
"""Hashed, revocable API tokens for the OnePlus 9 public gateway.

Plaintext tokens are only returned by the CLI at creation time. The database
stores SHA-256 hashes plus a short prefix for lookup/audit.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(
    os.environ.get(
        "GATEWAY_TOKEN_DB", "/data/data/com.termux/files/home/gateway_tokens.db"
    )
)
TOKEN_PREFIX = "pgw_"
PREFIX_LEN = 12
LAST_USED_THROTTLE = 60


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                expires_at INTEGER,
                last_used_at INTEGER,
                last_used_ip TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tokens_prefix ON api_tokens(prefix);
            CREATE TABLE IF NOT EXISTS token_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                token_id INTEGER,
                prefix TEXT,
                action TEXT NOT NULL,
                ip TEXT,
                detail TEXT
            );
            """
        )
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _audit(conn, token_id, prefix, action, ip, detail=""):
    conn.execute(
        "INSERT INTO token_audit (ts, token_id, prefix, action, ip, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(time.time()), token_id, prefix, action, ip, detail),
    )


def verify_token(token: str, client_ip: str) -> tuple[bool, int | None, str]:
    if not token.startswith(TOKEN_PREFIX):
        with _db() as conn:
            _audit(conn, None, token[:PREFIX_LEN], "auth_failed", client_ip, "unknown_prefix")
        return False, None, "unknown_prefix"

    prefix = token[:PREFIX_LEN]
    now = int(time.time())
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, token_hash, enabled, expires_at, last_used_at "
            "FROM api_tokens WHERE prefix = ?",
            (prefix,),
        ).fetchall()
        for row in rows:
            if not hmac.compare_digest(row["token_hash"], _hash(token)):
                continue
            if not row["enabled"]:
                _audit(conn, row["id"], prefix, "auth_failed", client_ip, "disabled")
                return False, row["id"], "disabled"
            if row["expires_at"] is not None and now >= row["expires_at"]:
                _audit(conn, row["id"], prefix, "auth_failed", client_ip, "expired")
                return False, row["id"], "expired"
            if row["last_used_at"] is None or now - row["last_used_at"] >= LAST_USED_THROTTLE:
                conn.execute(
                    "UPDATE api_tokens SET last_used_at = ?, last_used_ip = ? WHERE id = ?",
                    (now, client_ip, row["id"]),
                )
            return True, row["id"], "ok"
        _audit(conn, None, prefix, "auth_failed", client_ip, "unknown_token")
        return False, None, "unknown_token"


def create_token(name: str, days: int | None = None, out_path: str | None = None) -> dict[str, Any]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    prefix = token[:PREFIX_LEN]
    now = int(time.time())
    expires_at = now + days * 86400 if days else None
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO api_tokens (name, token_hash, prefix, enabled, created_at, expires_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (name, _hash(token), prefix, now, expires_at),
        )
        token_id = cur.lastrowid
        _audit(conn, token_id, prefix, "created", "cli", f"name={name};expires_at={expires_at}")
    if out_path:
        path = Path(out_path).expanduser()
        path.write_text(token + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return {
        "id": token_id,
        "name": name,
        "prefix": prefix,
        "expires_at": expires_at,
        "token": token,
        "out_path": out_path,
    }


def list_tokens() -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, name, prefix, enabled, created_at, expires_at, last_used_at, last_used_ip "
            "FROM api_tokens ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]


def revoke_token(token_id: int | None = None, prefix: str | None = None) -> int:
    with _db() as conn:
        if token_id is not None:
            rows = conn.execute("SELECT id, prefix FROM api_tokens WHERE id = ?", (token_id,)).fetchall()
            cur = conn.execute("UPDATE api_tokens SET enabled = 0 WHERE id = ?", (token_id,))
        elif prefix:
            rows = conn.execute("SELECT id, prefix FROM api_tokens WHERE prefix = ?", (prefix,)).fetchall()
            cur = conn.execute("UPDATE api_tokens SET enabled = 0 WHERE prefix = ?", (prefix,))
        else:
            raise ValueError("token_id or prefix required")
        for row in rows:
            _audit(conn, row["id"], row["prefix"], "revoked", "cli")
        return cur.rowcount


def rotate_token(token_id: int, days: int | None = None, out_path: str | None = None) -> dict[str, Any]:
    with _db() as conn:
        row = conn.execute("SELECT id, name FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        raise ValueError("token id not found")
    revoke_token(token_id=token_id)
    return create_token(row["name"], days=days, out_path=out_path)


def recent_audit(limit: int = 50) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT ts, token_id, prefix, action, ip, detail FROM token_audit "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _fmt_ts(value: int | None) -> str:
    if value is None:
        return "-"
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gateway token management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--days", type=int, default=None)
    p_create.add_argument("--out", default=None)

    sub.add_parser("list")

    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("--id", type=int)
    p_revoke.add_argument("--prefix")

    p_rotate = sub.add_parser("rotate")
    p_rotate.add_argument("--id", type=int, required=True)
    p_rotate.add_argument("--days", type=int, default=None)
    p_rotate.add_argument("--out", default=None)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--limit", type=int, default=50)

    args = parser.parse_args()
    init_db()

    if args.cmd == "create":
        result = create_token(args.name, args.days, args.out)
        print(
            f"CREATED id={result['id']} name={result['name']} "
            f"prefix={result['prefix']} expires={_fmt_ts(result['expires_at'])}"
        )
        if result["out_path"]:
            print(f"token written to {result['out_path']} (chmod 600; send once, then delete the file)")
        else:
            print("TOKEN (shown once):")
            print(result["token"])
    elif args.cmd == "list":
        for row in list_tokens():
            print(
                f"id={row['id']} name={row['name']} prefix={row['prefix']} "
                f"enabled={row['enabled']} created={_fmt_ts(row['created_at'])} "
                f"expires={_fmt_ts(row['expires_at'])} "
                f"last_used={_fmt_ts(row['last_used_at'])} ip={row['last_used_ip'] or '-'}"
            )
    elif args.cmd == "revoke":
        count = revoke_token(token_id=args.id, prefix=args.prefix)
        print(f"REVOKED {count} token(s)")
    elif args.cmd == "rotate":
        result = rotate_token(args.id, args.days, args.out)
        print(
            f"ROTATED new_id={result['id']} prefix={result['prefix']} "
            f"expires={_fmt_ts(result['expires_at'])}"
        )
        if result["out_path"]:
            print(f"token written to {result['out_path']} (chmod 600; send once, then delete the file)")
        else:
            print("TOKEN (shown once):")
            print(result["token"])
    elif args.cmd == "audit":
        for row in recent_audit(args.limit):
            print(
                f"{_fmt_ts(row['ts'])} action={row['action']} token={row['token_id']} "
                f"prefix={row['prefix']} ip={row['ip']} detail={row['detail']}"
            )


if __name__ == "__main__":
    main()
