from nephthys.database.raw_migration import raw_migration

ID = "2026-11-16T23:00:00:000000"
VERSION = "1.34.0"
DESCRIPTION = "Add ai_reply_at to tickets"


async def forwards():
    return raw_migration(
        migration_id=ID,
        app_name="nephthys",
        description=DESCRIPTION,
        forwards="""
ALTER TABLE "Ticket" ADD COLUMN IF NOT EXISTS "aiReplyAt" TIMESTAMPTZ;
""",
        backwards="""
ALTER TABLE "Ticket" DROP COLUMN IF EXISTS "aiReplyAt";
""",
    )
