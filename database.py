import json
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent / "data" / "blueguard.sqlite3"


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        );
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, guild_id INTEGER, text TEXT NOT NULL,
            due_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tags (
            guild_id INTEGER NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
            author_id INTEGER NOT NULL, PRIMARY KEY (guild_id, name)
        );
        CREATE TABLE IF NOT EXISTS balances (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, coins INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS activity (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
            messages INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS points (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            prize TEXT NOT NULL, host_id INTEGER NOT NULL, ends_at REAL NOT NULL, ended INTEGER NOT NULL DEFAULT 0,
            winner_count INTEGER NOT NULL DEFAULT 1, drop_mode INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            message_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS reaction_roles (
            message_id INTEGER NOT NULL, emoji TEXT NOT NULL, role_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, emoji)
        );
        CREATE TABLE IF NOT EXISTS starboard_posts (
            source_message_id INTEGER PRIMARY KEY, board_message_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invite_counts (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS giveaway_winners (
            message_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, user_id)
        );
        """)
        for statement in (
            "ALTER TABLE giveaways ADD COLUMN winner_count INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE giveaways ADD COLUMN drop_mode INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await db.execute(statement)
            except aiosqlite.OperationalError:
                pass
        await db.commit()


async def get_setting(guild_id: int, key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key)) as cur:
            row = await cur.fetchone()
    return json.loads(row[0]) if row else default


async def set_setting(guild_id: int, key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            (guild_id, key, json.dumps(value)),
        )
        await db.commit()


async def add_case(guild_id, user_id, moderator_id, action, reason, created_at, expires_at=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO cases(guild_id,user_id,moderator_id,action,reason,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (guild_id, user_id, moderator_id, action, reason, created_at, expires_at),
        )
        await db.commit()
        return cur.lastrowid

