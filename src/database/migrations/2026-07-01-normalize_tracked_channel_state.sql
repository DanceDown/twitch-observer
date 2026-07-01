-- Normalize tracked Twitch live state into one global table.
-- Safe for:
-- 1. older databases that still store live state on channel rows
-- 2. newer databases where those legacy columns are already gone

CREATE TABLE IF NOT EXISTS tracked_channel_state (
    twitch_channel_id   TEXT PRIMARY KEY,
    is_live             BOOLEAN,
    last_live_status_at TIMESTAMPTZ
);

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'channel'
          AND column_name = 'is_live'
    ) AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'channel'
          AND column_name = 'last_live_status_at'
    ) THEN
        EXECUTE $backfill$
            INSERT INTO tracked_channel_state (twitch_channel_id, is_live, last_live_status_at)
            SELECT winner.twitch_channel_id, winner.is_live, winner.last_live_status_at
            FROM (
                SELECT DISTINCT ON (c.twitch_channel_id)
                    c.twitch_channel_id,
                    c.is_live,
                    c.last_live_status_at
                FROM channel AS c
                ORDER BY
                    c.twitch_channel_id,
                    c.last_live_status_at DESC NULLS LAST,
                    c.thread_id DESC
            ) AS winner
            ON CONFLICT (twitch_channel_id) DO UPDATE
            SET is_live = EXCLUDED.is_live,
                last_live_status_at = EXCLUDED.last_live_status_at
        $backfill$;
    END IF;
END
$migration$;

ALTER TABLE channel DROP COLUMN IF EXISTS is_live;
ALTER TABLE channel DROP COLUMN IF EXISTS last_live_status_at;
