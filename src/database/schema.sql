-- PostgreSQL schema
-- Run on PostgreSQL 12+

----------------------------
-- TYPES
----------------------------
CREATE TYPE SUB_STATE_ENUM AS ENUM ('all', 'non_subs', 'subs');
CREATE TYPE OFFLINE_STATE_ENUM AS ENUM ('both', 'offline', 'online');
CREATE TYPE CHANNEL_SCOPE_MODE_ENUM AS ENUM ('all_tracked', 'only_selected', 'all_except_selected');
CREATE TYPE USER_SCOPE_MODE_ENUM AS ENUM ('all_users', 'all_tracked', 'only_selected', 'all_except_selected', 'all_tracked_except_selected');

----------------------------
-- Twitch accounts
----------------------------
CREATE TABLE twitch_account (
    account_id        SERIAL PRIMARY KEY,
    discord_user_id   BIGINT      NOT NULL,
    twitch_user_id    TEXT        NOT NULL,
    twitch_login      TEXT        NOT NULL,
    client_id         TEXT        NOT NULL,
    updated_at        TIMESTAMPTZ,
    access_token      TEXT,
    refresh_token     TEXT,
    expires_at        TIMESTAMPTZ,
    scope             JSONB,
    token_type        TEXT
);

CREATE INDEX idx_twitch_account_discord_user_id
    ON twitch_account(discord_user_id);

CREATE INDEX idx_twitch_account_twitch_user_id
    ON twitch_account(twitch_user_id);

CREATE TABLE twitch_device_flow (
    discord_channel_id BIGINT PRIMARY KEY,
    discord_user_id    BIGINT NOT NULL,
    device_code        TEXT        NOT NULL,
    user_code          TEXT        NOT NULL,
    verification_uri   TEXT        NOT NULL,
    interval_seconds   INTEGER     NOT NULL,
    expires_at         TIMESTAMPTZ NOT NULL,
    scope              JSONB       NOT NULL DEFAULT '[]'::jsonb,
    status             TEXT        NOT NULL DEFAULT 'pending',
    last_error         TEXT,
    last_polled_at     TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_twitch_device_flow_status CHECK (status IN ('pending', 'failed'))
);

CREATE INDEX idx_twitch_device_flow_status
    ON twitch_device_flow(status, expires_at);

CREATE INDEX idx_twitch_device_flow_discord_user_id
    ON twitch_device_flow(discord_user_id);

----------------------------
-- Thread
----------------------------
CREATE TABLE thread (
    thread_id             SERIAL PRIMARY KEY,
    owner_id              BIGINT NOT NULL,
    discord_channel_id    BIGINT NOT NULL,
    account_id            INTEGER REFERENCES twitch_account(account_id) ON DELETE SET NULL,
    enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    color                 TEXT,
    CONSTRAINT chk_thread_color_format CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT uniq_discord_channel UNIQUE (discord_channel_id)
);

----------------------------
-- Channel source subscriptions
----------------------------
CREATE TABLE channel (
    thread_id           INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    twitch_channel_id   TEXT NOT NULL,
    color               TEXT,
    PRIMARY KEY (thread_id, twitch_channel_id),
    CONSTRAINT chk_channel_color_format CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$')
);

CREATE INDEX idx_channel_twitch_channel_id
    ON channel(twitch_channel_id);

CREATE TABLE tracked_user (
    thread_id         INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    twitch_user_id    TEXT NOT NULL,
    PRIMARY KEY (thread_id, twitch_user_id)
);

CREATE INDEX idx_tracked_user_twitch_user_id
    ON tracked_user(twitch_user_id);

----------------------------
-- Pattern rules
----------------------------
CREATE TABLE pattern (
    thread_id            INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    p_index              INTEGER NOT NULL,
    regex                TEXT NOT NULL,
    channel_scope_mode   CHANNEL_SCOPE_MODE_ENUM NOT NULL DEFAULT 'all_tracked',
    user_scope_mode      USER_SCOPE_MODE_ENUM NOT NULL DEFAULT 'all_users',
    sub_state            SUB_STATE_ENUM NOT NULL DEFAULT 'all',
    offline_state        OFFLINE_STATE_ENUM NOT NULL DEFAULT 'both',
    is_regex             BOOLEAN NOT NULL DEFAULT FALSE,
    case_sensitive       BOOLEAN NOT NULL DEFAULT FALSE,
    color                TEXT,
    disabled             BOOLEAN NOT NULL DEFAULT FALSE,
    notify               BOOLEAN NOT NULL DEFAULT TRUE,
    priority             SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (thread_id, p_index),
    CONSTRAINT chk_pattern_color_format CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_pattern_priority_range CHECK (priority BETWEEN 0 AND 9)
);

CREATE INDEX idx_pattern_thread_scope_mode
    ON pattern(thread_id, user_scope_mode);

CREATE INDEX idx_pattern_notify_active
    ON pattern(thread_id, disabled, notify);

CREATE TABLE pattern_channel_scope (
    thread_id           INTEGER NOT NULL,
    p_index             INTEGER NOT NULL,
    twitch_channel_id   TEXT NOT NULL,
    PRIMARY KEY (thread_id, p_index, twitch_channel_id),
    CONSTRAINT fk_pattern_channel_scope_pattern
        FOREIGN KEY (thread_id, p_index)
        REFERENCES pattern(thread_id, p_index)
        ON DELETE CASCADE,
    CONSTRAINT fk_pattern_channel_scope_channel
        FOREIGN KEY (thread_id, twitch_channel_id)
        REFERENCES channel(thread_id, twitch_channel_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_pattern_channel_scope_channel
    ON pattern_channel_scope(thread_id, twitch_channel_id);

CREATE TABLE pattern_user_scope (
    thread_id        INTEGER NOT NULL,
    p_index          INTEGER NOT NULL,
    twitch_user_id   TEXT NOT NULL,
    PRIMARY KEY (thread_id, p_index, twitch_user_id),
    CONSTRAINT fk_pattern_user_scope_pattern
        FOREIGN KEY (thread_id, p_index)
        REFERENCES pattern(thread_id, p_index)
        ON DELETE CASCADE,
    CONSTRAINT fk_pattern_user_scope_tracked_user
        FOREIGN KEY (thread_id, twitch_user_id)
        REFERENCES tracked_user(thread_id, twitch_user_id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_pattern_user_scope_user
    ON pattern_user_scope(thread_id, twitch_user_id);

----------------------------
-- Auto-replies
----------------------------
CREATE TABLE reply (
    thread_id         INTEGER NOT NULL,
    p_index           INTEGER NOT NULL,
    reply_message     TEXT NOT NULL,
    reply_as_reply    BOOLEAN NOT NULL DEFAULT FALSE,
    disabled          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (thread_id, p_index),
    CONSTRAINT fk_reply_pattern
        FOREIGN KEY (thread_id, p_index)
        REFERENCES pattern(thread_id, p_index)
        ON DELETE CASCADE
);

CREATE INDEX idx_reply_thread_disabled
    ON reply(thread_id, disabled);

----------------------------
-- User permissions
----------------------------
CREATE TABLE user_permissions (
    discord_user_id   BIGINT NOT NULL,
    thread_id         INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    permissions       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (discord_user_id, thread_id)
);

----------------------------
-- Messages
----------------------------
CREATE TABLE message (
    message_id         TEXT PRIMARY KEY,
    twitch_channel_id  TEXT NOT NULL,
    timestamp          TIMESTAMPTZ NOT NULL,
    twitch_user_id     TEXT NOT NULL,
    username           TEXT NOT NULL,
    content            TEXT NOT NULL,
    is_reply_to        TEXT REFERENCES message(message_id) ON DELETE SET NULL,
    is_bot             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_message_username
    ON message(username);

CREATE INDEX idx_message_channel
    ON message(twitch_channel_id);

CREATE INDEX idx_message_timestamp
    ON message(timestamp);
