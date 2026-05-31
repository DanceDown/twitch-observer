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

CREATE TABLE twitch_user_cache (
    twitch_user_id       TEXT PRIMARY KEY,
    twitch_login         TEXT        NOT NULL,
    display_name         TEXT        NOT NULL,
    profile_image_url    TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_api_refresh_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_twitch_user_cache_login
    ON twitch_user_cache(twitch_login);

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
    language              TEXT NOT NULL DEFAULT 'english',
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
    is_live             BOOLEAN,
    last_live_status_at TIMESTAMPTZ,
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
    pattern_id           SERIAL PRIMARY KEY,
    thread_id            INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
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
    CONSTRAINT uniq_pattern_thread_internal_id UNIQUE (thread_id, pattern_id),
    CONSTRAINT chk_pattern_color_format CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_pattern_priority_range CHECK (priority BETWEEN 0 AND 9)
);

CREATE INDEX idx_pattern_thread_scope_mode
    ON pattern(thread_id, user_scope_mode);

CREATE INDEX idx_pattern_notify_active
    ON pattern(thread_id, disabled, notify);

CREATE TABLE pattern_channel_scope (
    thread_id           INTEGER NOT NULL,
    pattern_id             INTEGER NOT NULL,
    twitch_channel_id   TEXT NOT NULL,
    PRIMARY KEY (thread_id, pattern_id, twitch_channel_id),
    CONSTRAINT fk_pattern_channel_scope_pattern
        FOREIGN KEY (thread_id, pattern_id)
        REFERENCES pattern(thread_id, pattern_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_pattern_channel_scope_channel
        FOREIGN KEY (thread_id, twitch_channel_id)
        REFERENCES channel(thread_id, twitch_channel_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_pattern_channel_scope_channel
    ON pattern_channel_scope(thread_id, twitch_channel_id);

CREATE TABLE pattern_user_scope (
    thread_id        INTEGER NOT NULL,
    pattern_id          INTEGER NOT NULL,
    twitch_user_id   TEXT NOT NULL,
    PRIMARY KEY (thread_id, pattern_id, twitch_user_id),
    CONSTRAINT fk_pattern_user_scope_pattern
        FOREIGN KEY (thread_id, pattern_id)
        REFERENCES pattern(thread_id, pattern_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_pattern_user_scope_tracked_user
        FOREIGN KEY (thread_id, twitch_user_id)
        REFERENCES tracked_user(thread_id, twitch_user_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_pattern_user_scope_user
    ON pattern_user_scope(thread_id, twitch_user_id);

----------------------------
-- Auto-replies
----------------------------
CREATE TABLE reply (
    thread_id         INTEGER NOT NULL,
    pattern_id           INTEGER NOT NULL,
    reply_message     TEXT NOT NULL,
    reply_as_reply    BOOLEAN NOT NULL DEFAULT FALSE,
    disabled          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (thread_id, pattern_id),
    CONSTRAINT fk_reply_pattern
        FOREIGN KEY (thread_id, pattern_id)
        REFERENCES pattern(thread_id, pattern_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_reply_thread_disabled
    ON reply(thread_id, disabled);

CREATE TABLE adapter_event (
    event_id         SERIAL PRIMARY KEY,
    thread_id        INTEGER NOT NULL REFERENCES thread(thread_id) ON DELETE CASCADE,
    adapter_key      TEXT NOT NULL,
    subject_type     TEXT NOT NULL,
    subject_id       TEXT NOT NULL,
    event_key        TEXT NOT NULL,
    disabled         BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uniq_adapter_event
        UNIQUE (thread_id, adapter_key, subject_type, subject_id, event_key),
    CONSTRAINT chk_adapter_event_adapter_key
        CHECK (adapter_key <> ''),
    CONSTRAINT chk_adapter_event_subject_type
        CHECK (subject_type <> ''),
    CONSTRAINT chk_adapter_event_subject_id
        CHECK (subject_id <> ''),
    CONSTRAINT chk_adapter_event_event_key
        CHECK (event_key <> '')
);

CREATE INDEX idx_adapter_event_lookup
    ON adapter_event(adapter_key, subject_type, subject_id, event_key, disabled);

CREATE TABLE adapter_event_action (
    event_id            INTEGER NOT NULL REFERENCES adapter_event(event_id) ON DELETE CASCADE,
    action_type         TEXT NOT NULL,
    message_template    TEXT,
    reply_as_reply      BOOLEAN NOT NULL DEFAULT FALSE,
    color               TEXT,
    disabled            BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (event_id, action_type),
    CONSTRAINT chk_adapter_event_action_type
        CHECK (action_type <> ''),
    CONSTRAINT chk_adapter_event_action_color_format
        CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$')
);

CREATE INDEX idx_adapter_event_action_lookup
    ON adapter_event_action(action_type, disabled);

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
