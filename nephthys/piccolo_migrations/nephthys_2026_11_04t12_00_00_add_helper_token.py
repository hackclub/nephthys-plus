from nephthys.database.raw_migration import raw_migration

ID = "2026-11-04T12:00:00:000000"
VERSION = "1.34.0"
DESCRIPTION = "Add helper_token table"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
CREATE TABLE helper_token (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL UNIQUE REFERENCES "User"(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
""",
        backwards="""
DROP TABLE IF EXISTS helper_token;
""",
    )
