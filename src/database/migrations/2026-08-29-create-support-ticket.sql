CREATE TABLE IF NOT EXISTS support_ticket (
    ticket_id                    SERIAL PRIMARY KEY,
    source_discord_channel_id    BIGINT      NOT NULL,
    requester_discord_user_id    BIGINT      NOT NULL,
    category                     TEXT        NOT NULL,
    title                        TEXT        NOT NULL,
    description                  TEXT        NOT NULL,
    status                       TEXT        NOT NULL DEFAULT 'open',
    language                     TEXT        NOT NULL DEFAULT 'english',
    support_message_id           BIGINT,
    response_subject             TEXT,
    response_body                TEXT,
    responded_by_discord_user_id BIGINT,
    responded_at                 TIMESTAMPTZ,
    closed_by_discord_user_id    BIGINT,
    closed_at                    TIMESTAMPTZ,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_support_ticket_category CHECK (category IN ('bug', 'question', 'idea', 'other')),
    CONSTRAINT chk_support_ticket_status CHECK (status IN ('open', 'answered', 'closed')),
    CONSTRAINT chk_support_ticket_language CHECK (language <> '')
);

CREATE INDEX IF NOT EXISTS idx_support_ticket_status_message
    ON support_ticket(status, support_message_id)
    WHERE support_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_support_ticket_source_channel
    ON support_ticket(source_discord_channel_id);

CREATE INDEX IF NOT EXISTS idx_support_ticket_requester
    ON support_ticket(requester_discord_user_id);
