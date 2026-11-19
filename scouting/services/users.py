"""사용자 등록·인증·역할 (CONTRACT §6.3). 비밀번호: pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass

from scouting.db import transaction

ITERATIONS = 200_000
ROLES = ("scout", "admin")
MIN_PASSWORD_LEN = 4


@dataclass(frozen=True)
class User:
    user_id: int
    username: str
    role: str


def hash_password(password: str, *, iterations: int = ITERATIONS, salt: bytes | None = None) -> str:
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("dummy", salt=b"\0" * 16)


def username_problem(conn: sqlite3.Connection, username: str) -> str | None:
    """사용자명이 가입 불가하면 사유(한국어), 가능하면 None. 비밀번호를 받기 전에 쓴다."""
    username = (username or "").strip()
    if not 3 <= len(username) <= 32:
        return "사용자명은 3~32자여야 합니다."
    if conn.execute("SELECT 1 FROM app_user WHERE username = ?", (username,)).fetchone():
        return "이미 사용 중인 사용자명입니다."
    return None


def register(conn: sqlite3.Connection, username: str, password: str, role: str = "scout") -> int:
    username = (username or "").strip()
    if not 3 <= len(username) <= 32:
        raise ValueError("사용자명은 3~32자여야 합니다.")
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다.")
    if role not in ROLES:
        raise ValueError("역할은 scout 또는 admin 이어야 합니다.")
    pw_hash = hash_password(password)
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO app_user (username, password_hash, role) VALUES (?, ?, ?)",
                (username, pw_hash, role),
            )
            return int(cur.lastrowid)
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise ValueError("이미 사용 중인 사용자명입니다.") from e
        raise


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    row = conn.execute(
        "SELECT user_id, username, role, password_hash FROM app_user WHERE username = ?",
        ((username or "").strip(),),
    ).fetchone()
    if row is None:
        verify_password(password or "", _DUMMY_HASH)  # 존재 여부에 따른 응답 시간 차이 완화
        return None
    if not verify_password(password or "", row["password_hash"]):
        return None
    return User(row["user_id"], row["username"], row["role"])


def require_admin(conn: sqlite3.Connection, actor: User | None) -> None:
    """actor 객체가 아니라 DB에 저장된 현재 역할로 admin 여부를 검사한다."""
    if actor is None:
        raise PermissionError("관리자 권한이 필요합니다.")
    row = conn.execute("SELECT role FROM app_user WHERE user_id = ?", (actor.user_id,)).fetchone()
    if row is None or row["role"] != "admin":
        raise PermissionError("관리자 권한이 필요합니다.")


def set_role(conn: sqlite3.Connection, actor: User, target_user_id: int, role: str) -> None:
    require_admin(conn, actor)
    if role not in ROLES:
        raise ValueError("역할은 scout 또는 admin 이어야 합니다.")
    with transaction(conn):
        cur_role = conn.execute(
            "SELECT role FROM app_user WHERE user_id = ?", (target_user_id,)
        ).fetchone()
        if cur_role is None:
            raise ValueError("존재하지 않는 사용자입니다.")
        if cur_role["role"] == "admin" and role != "admin":
            (n_admin,) = conn.execute("SELECT COUNT(*) FROM app_user WHERE role = 'admin'").fetchone()
            if n_admin <= 1:
                raise ValueError("마지막 관리자는 강등할 수 없습니다.")
        conn.execute("UPDATE app_user SET role = ? WHERE user_id = ?", (role, target_user_id))


def list_users(conn: sqlite3.Connection, actor: User) -> list[dict]:
    require_admin(conn, actor)
    return [dict(r) for r in conn.execute("SELECT * FROM v_user_activity ORDER BY user_id")]
