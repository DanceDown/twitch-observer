from __future__ import annotations

"""PostgreSQL database connection helpers."""

from dataclasses import dataclass

import psycopg

from src.config import AppConfig


@dataclass(slots=True)
class PostgresDatabase:
    """Thin wrapper around a psycopg connection."""

    config: AppConfig
    connection: psycopg.Connection | None = None

    def connect(self) -> None:
        """Open the PostgreSQL connection lazily."""
        if self.connection is None or self.connection.closed:
            self.connection = psycopg.connect(self.config.postgres_dsn, autocommit=True)

    def close(self) -> None:
        """Close the PostgreSQL connection if it is open."""
        if self.connection is not None and not self.connection.closed:
            self.connection.close()

    def healthcheck(self) -> None:
        """Validate that PostgreSQL is reachable."""
        self.connect()
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def ensure_schema_compatibility(self) -> None:
        """Apply lightweight compatibility migrations for existing local databases."""
        self.connect()
        assert self.connection is not None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE thread
                ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'english'
                """
            )
            cursor.execute(
                """
                UPDATE thread
                SET language = 'english'
                WHERE language IS NULL OR btrim(language) = ''
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                ALTER COLUMN color DROP NOT NULL
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                ALTER COLUMN color DROP DEFAULT
                """
            )
            cursor.execute(
                """
                ALTER TABLE thread
                DROP COLUMN IF EXISTS use_twitch_colors
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON e.enumtypid = t.oid
                        WHERE t.typname = 'user_scope_mode_enum' AND e.enumlabel = 'all_tracked'
                    ) THEN
                        ALTER TYPE USER_SCOPE_MODE_ENUM ADD VALUE 'all_tracked';
                    END IF;
                END $$;
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_type t
                        JOIN pg_enum e ON e.enumtypid = t.oid
                        WHERE t.typname = 'user_scope_mode_enum' AND e.enumlabel = 'all_tracked_except_selected'
                    ) THEN
                        ALTER TYPE USER_SCOPE_MODE_ENUM ADD VALUE 'all_tracked_except_selected';
                    END IF;
                END $$;
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_user (
                    thread_id INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
                    twitch_user_id TEXT NOT NULL,
                    PRIMARY KEY (thread_id, twitch_user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tracked_user_twitch_user_id
                ON tracked_user(twitch_user_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS twitch_user_cache (
                    twitch_user_id TEXT PRIMARY KEY,
                    twitch_login TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    profile_image_url TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_api_refresh_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_twitch_user_cache_login
                ON twitch_user_cache(twitch_login)
                """
            )
            cursor.execute(
                """
                ALTER TABLE channel
                ADD COLUMN IF NOT EXISTS is_live BOOLEAN
                """
            )
            cursor.execute(
                """
                ALTER TABLE channel
                ADD COLUMN IF NOT EXISTS last_live_status_at TIMESTAMPTZ
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS adapter_event (
                    event_id SERIAL PRIMARY KEY,
                    thread_id INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
                    adapter_key TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    disabled BOOLEAN NOT NULL DEFAULT FALSE,
                    CONSTRAINT uniq_adapter_event
                        UNIQUE (thread_id, adapter_key, subject_type, subject_id, event_key)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_adapter_event_lookup
                ON adapter_event(adapter_key, subject_type, subject_id, event_key, disabled)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS adapter_event_action (
                    event_id INTEGER NOT NULL REFERENCES adapter_event(event_id) ON DELETE CASCADE,
                    action_type TEXT NOT NULL,
                    message_template TEXT,
                    reply_as_reply BOOLEAN NOT NULL DEFAULT FALSE,
                    disabled BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (event_id, action_type)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_adapter_event_action_lookup
                ON adapter_event_action(action_type, disabled)
                """
            )
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF to_regclass('public.channel_event_reply') IS NOT NULL THEN
                        INSERT INTO adapter_event (thread_id, adapter_key, subject_type, subject_id, event_key, disabled)
                        SELECT cer.thread_id,
                               'twitch',
                               'channel',
                               cer.twitch_channel_id,
                               CASE cer.event_state WHEN 'online' THEN 'stream.online' ELSE 'stream.offline' END,
                               FALSE
                        FROM channel_event_reply cer
                        ON CONFLICT (thread_id, adapter_key, subject_type, subject_id, event_key) DO NOTHING;

                        INSERT INTO adapter_event_action (event_id, action_type, message_template, reply_as_reply, disabled)
                        SELECT ae.event_id,
                               'twitch_send_message',
                               cer.reply_message,
                               FALSE,
                               cer.disabled
                        FROM channel_event_reply cer
                        JOIN adapter_event ae
                          ON ae.thread_id = cer.thread_id
                         AND ae.adapter_key = 'twitch'
                         AND ae.subject_type = 'channel'
                         AND ae.subject_id = cer.twitch_channel_id
                         AND ae.event_key = CASE cer.event_state WHEN 'online' THEN 'stream.online' ELSE 'stream.offline' END
                        ON CONFLICT (event_id, action_type)
                        DO UPDATE SET
                            message_template = EXCLUDED.message_template,
                            disabled = EXCLUDED.disabled;
                    END IF;
                END $$;
                """
            )
