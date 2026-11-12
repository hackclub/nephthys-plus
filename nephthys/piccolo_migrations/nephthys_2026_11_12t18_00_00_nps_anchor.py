from nephthys.database.raw_migration import raw_migration

ID = "2026-11-12T18:00:00:000000"
VERSION = "1.34.0"
DESCRIPTION = "Add nps_anchor table"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
CREATE TABLE nps_anchor (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL UNIQUE,
    message_ts TEXT NOT NULL
);
""",
        backwards="""
DROP TABLE IF EXISTS nps_anchor;
""",
    )
