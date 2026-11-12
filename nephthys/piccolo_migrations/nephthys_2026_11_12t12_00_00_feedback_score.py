from nephthys.database.raw_migration import raw_migration

ID = "2026-11-12T12:00:00:000000"
VERSION = "1.34.0"
DESCRIPTION = "Add NPS score to Feedback"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
ALTER TABLE "Feedback" ADD COLUMN score INT;
""",
        backwards="""
ALTER TABLE "Feedback" DROP COLUMN IF EXISTS score;
""",
    )
