-- Ensure every tracked Twitch channel has a global live-state row.
-- This repairs databases imported without tracked_channel_state data.

INSERT INTO tracked_channel_state (twitch_channel_id)
SELECT DISTINCT twitch_channel_id
FROM channel
ON CONFLICT (twitch_channel_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_message_channel_timestamp
    ON message(twitch_channel_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_thread_message_match_message
    ON thread_message_match(message_id);
