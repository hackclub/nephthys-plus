from nephthys.database.raw_migration import raw_migration

ID = "2026-11-18T12:00:00:000000"
VERSION = "1.34.0"
DESCRIPTION = "Add anchor, anchor_proposal and anchor_approval tables"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
CREATE TABLE anchor (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    message_ts TEXT,
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE anchor_proposal (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL,
    proposer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE anchor_approval (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES anchor_proposal(id) ON DELETE CASCADE,
    approver TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (proposal_id, approver)
);
""",
        backwards="""
DROP TABLE IF EXISTS anchor_approval;
DROP TABLE IF EXISTS anchor_proposal;
DROP TABLE IF EXISTS anchor;
""",
    )
