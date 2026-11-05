from nephthys.database.raw_migration import raw_migration

ID = "2026-11-05T14:00:00:000000"
VERSION = "1.35.0"
DESCRIPTION = "Add description and always_tag columns to Tag table"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
ALTER TABLE "Tag"
    ADD COLUMN description TEXT,
    ADD COLUMN "alwaysTag" BOOLEAN NOT NULL DEFAULT FALSE;
""",
        backwards="""
ALTER TABLE "Tag"
    DROP COLUMN IF EXISTS description,
    DROP COLUMN IF EXISTS "alwaysTag";
""",
    )