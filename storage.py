from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import keyring

APP_NAME = "TelegramVideoManager"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "history.sqlite3"

DEFAULT_CONFIG = {
    "api_id": "",
    "phone": "",
    "source_group": "-1003929455385",
    "destination_group": "",
    "create_topics": True,
    "keep_caption": True,
    "search_limit": 5000,
}


def load_config():
    data = DEFAULT_CONFIG.copy()

    if CONFIG_PATH.exists():
        try:
            saved = json.loads(
                CONFIG_PATH.read_text(encoding="utf-8")
            )

            if isinstance(saved, dict):
                data.update(saved)

        except Exception:
            pass

    return data


def save_config(data):
    merged = DEFAULT_CONFIG.copy()
    merged.update(data)

    CONFIG_PATH.write_text(
        json.dumps(
            merged,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def save_api_hash(value: str):
    value = (value or "").strip()

    if value:
        keyring.set_password(
            APP_NAME,
            "api_hash",
            value
        )


def load_api_hash():
    try:
        return (
            keyring.get_password(
                APP_NAME,
                "api_hash"
            )
            or ""
        )

    except Exception:
        return ""


def delete_api_hash():
    try:
        keyring.delete_password(
            APP_NAME,
            "api_hash"
        )

    except Exception:
        pass


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_history (
            source_group INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            destination_group INTEGER NOT NULL,
            destination_message_id INTEGER,
            hashtag TEXT NOT NULL,
            topic_title TEXT NOT NULL,
            topic_id INTEGER,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (
                source_group,
                source_message_id,
                destination_group
            )
        )
        """
    )

    conn.commit()

    return conn


def already_sent(
    source_group,
    message_id,
    destination_group
):
    with _db() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM sent_history
            WHERE
                source_group=?
                AND source_message_id=?
                AND destination_group=?
            LIMIT 1
            """,
            (
                int(source_group),
                int(message_id),
                int(destination_group),
            )
        ).fetchone()

        return row is not None


def mark_sent(
    source_group,
    message_id,
    destination_group,
    destination_message_id,
    hashtag,
    topic_title,
    topic_id
):
    with _db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sent_history (
                source_group,
                source_message_id,
                destination_group,
                destination_message_id,
                hashtag,
                topic_title,
                topic_id,
                sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(source_group),
                int(message_id),
                int(destination_group),
                (
                    int(destination_message_id)
                    if destination_message_id
                    else None
                ),
                hashtag,
                topic_title,
                (
                    int(topic_id)
                    if topic_id
                    else None
                ),
                datetime.now().isoformat(
                    timespec="seconds"
                ),
            )
        )

        conn.commit()


def get_history(limit=1000):
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sent_history
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (int(limit),)
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


def clear_history():
    with _db() as conn:
        conn.execute(
            "DELETE FROM sent_history"
        )

        conn.commit()
