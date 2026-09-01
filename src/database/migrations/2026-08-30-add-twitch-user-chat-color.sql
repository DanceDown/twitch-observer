ALTER TABLE twitch_user_cache
    ADD COLUMN IF NOT EXISTS chat_color TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_twitch_user_cache_chat_color_format'
    ) THEN
        ALTER TABLE twitch_user_cache
            ADD CONSTRAINT chk_twitch_user_cache_chat_color_format
            CHECK (chat_color IS NULL OR chat_color = '' OR chat_color ~ '^#[0-9A-Fa-f]{6}$');
    END IF;
END $$;
