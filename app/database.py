"""Database connection and session."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.settings_manager import settings
import os

# use TEST_DATABASE_URL during testing, otherwise fall back to configured URL
# in settings.  The application expects a PostgreSQL compatible URI; old
# SQLite logic has been removed as this project now starts fresh with
# Postgres only.
db_url = os.getenv("TEST_DATABASE_URL", settings.database_url)

# Railway (and some other platforms) provide DATABASE_URL as plain
# "postgresql://" or "postgres://".  SQLAlchemy's async engine requires the
# asyncpg dialect, so rewrite the scheme when it is missing.
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# If the database URL refers to SQLite we need the StaticPool/"
# check_same_thread" combination so that an in-memory database survives
# across multiple connections.  This is primarily for the test suite when
# ``TEST_DATABASE_URL`` is set to a memory URL; production (Postgres) is
# unaffected.
engine_kwargs: dict = {"echo": False}
if db_url.startswith("sqlite"):
    from sqlalchemy.pool import StaticPool

    # treat URL as URI (needed when using query params like cache=shared)
    engine_kwargs.update(
        {
            "connect_args": {"check_same_thread": False, "uri": True},
            "poolclass": StaticPool,
        }
    )

engine = create_async_engine(
    db_url,
    **engine_kwargs,
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# SQLite-specific migration helpers removed: starting fresh with PostgreSQL.
# A clean database will be created by init_db() using SQLAlchemy metadata.


async def _run_migrations(conn) -> None:
    """Apply incremental schema changes to existing databases.

    DDL is idempotent (IF NOT EXISTS, etc.). One-time data backfills are
    gated via ``_app_schema_migrations`` so they do not overwrite newer state
    on every startup.
    """
    from sqlalchemy import text

    # Postgres-only: ADD COLUMN IF NOT EXISTS is not valid on SQLite builds used in CI;
    # tests use create_all() from models (schema already current).
    if conn.dialect.name != "postgresql":
        if conn.dialect.name == "sqlite":
            try:
                res = await conn.execute(text("PRAGMA table_info(direct_email)"))
                cols = {r[1] for r in res.fetchall()}
                if "last_opened_at" not in cols:
                    await conn.execute(text("ALTER TABLE direct_email ADD COLUMN last_opened_at DATETIME NULL"))
                if "open_history" not in cols:
                    await conn.execute(text("ALTER TABLE direct_email ADD COLUMN open_history JSON NULL"))
                if "click_count" not in cols:
                    await conn.execute(text("ALTER TABLE direct_email ADD COLUMN click_count INTEGER DEFAULT 0"))
                if "click_history" not in cols:
                    await conn.execute(text("ALTER TABLE direct_email ADD COLUMN click_history JSON NULL"))
                res_inbox = await conn.execute(text("PRAGMA table_info(inbox)"))
                inbox_cols = {r[1] for r in res_inbox.fetchall()}
                if "inbound_type" not in inbox_cols:
                    await conn.execute(text("ALTER TABLE inbox ADD COLUMN inbound_type VARCHAR(32) NOT NULL DEFAULT 'imap'"))
                if "outbound_provider" not in inbox_cols:
                    await conn.execute(text("ALTER TABLE inbox ADD COLUMN outbound_provider VARCHAR(32) NOT NULL DEFAULT 'smtp'"))
                res_camp = await conn.execute(text("PRAGMA table_info(campaign)"))
                camp_cols = {r[1] for r in res_camp.fetchall()}
                if "archived" not in camp_cols:
                    await conn.execute(text("ALTER TABLE campaign ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0"))
                res_cl = await conn.execute(text("PRAGMA table_info(campaign_lead)"))
                cl_cols = {r[1] for r in res_cl.fetchall()}
                if "failure_reason" not in cl_cols:
                    await conn.execute(text("ALTER TABLE campaign_lead ADD COLUMN failure_reason TEXT NULL"))
                if "bounce_type" not in cl_cols:
                    await conn.execute(text("ALTER TABLE campaign_lead ADD COLUMN bounce_type VARCHAR(32) NULL"))
                await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_email ON lead(email)"))
                await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_lead ON campaign_lead(campaign_id, lead_id)"))
            except Exception:
                pass
        return

    pg_alters = [
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS inbound_type VARCHAR(32) NOT NULL DEFAULT 'imap'",
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS outbound_provider VARCHAR(32) NOT NULL DEFAULT 'smtp'",
        "ALTER TABLE campaign ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE campaign_lead ADD COLUMN IF NOT EXISTS failure_reason TEXT NULL",
        "ALTER TABLE campaign_lead ADD COLUMN IF NOT EXISTS bounce_type VARCHAR(32) NULL",
        "ALTER TABLE direct_email ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMP WITHOUT TIME ZONE NULL",
        "ALTER TABLE direct_email ADD COLUMN IF NOT EXISTS open_history JSONB DEFAULT '[]'",
        "ALTER TABLE direct_email ADD COLUMN IF NOT EXISTS click_count INTEGER DEFAULT 0",
        "ALTER TABLE direct_email ADD COLUMN IF NOT EXISTS click_history JSONB DEFAULT '[]'",
        # 2026-03-24: ramp-up starting number (default 1 preserves old behaviour)
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS ramp_up_start INTEGER NOT NULL DEFAULT 1",
        # 2026-03-24: track when ramp-up was last enabled (NULL = use created_at as fallback)
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS ramp_up_started_at TIMESTAMP WITHOUT TIME ZONE NULL",
        # 2026-03-25: per-campaign enrollment status (lead.status is no longer used for this)
        "ALTER TABLE campaign_lead ADD COLUMN IF NOT EXISTS enrollment_status VARCHAR(32) NOT NULL DEFAULT 'active'",
        # 2026-03-29: Beacon standalone tracking proxy (per inbox)
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS beacon_base_url VARCHAR(512) NULL",
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS beacon_setup_token VARCHAR(128) NULL",
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS beacon_webhook_secret VARCHAR(256) NULL",
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS beacon_connected BOOLEAN NOT NULL DEFAULT FALSE",
        # 2026-05-21: one-time OAuth connect URL tokens
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS connect_token VARCHAR(256) NULL",
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS connect_token_expires_at TIMESTAMP WITHOUT TIME ZONE NULL",
        # 2026-05-21: ramp-up step size (emails added per day during warm-up)
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS ramp_up_step_size INTEGER NOT NULL DEFAULT 1",
        # 2026-05-21: track when ramp-up was paused (for freezing warm-up)
        "ALTER TABLE inbox ADD COLUMN IF NOT EXISTS ramp_up_paused_at TIMESTAMP WITHOUT TIME ZONE NULL",
        # 2026-05-22: personalized sequence fallbacks
        "ALTER TABLE sequence ADD COLUMN IF NOT EXISTS fallback_subject VARCHAR(512)",
        "ALTER TABLE sequence ADD COLUMN IF NOT EXISTS fallback_body TEXT",
        # 2026-05-22: custom email override body made nullable (optional body)
        "ALTER TABLE custom_email_override ALTER COLUMN body DROP NOT NULL",
        # 2026-05-22: personalized sequence type column (standard|personalized)
        "ALTER TABLE sequence ADD COLUMN IF NOT EXISTS sequence_type VARCHAR(32) NOT NULL DEFAULT 'standard'",
        # 2026-05-23: pre-assigned A/B variant on queue slots
        "ALTER TABLE queue_slot ADD COLUMN IF NOT EXISTS variant_id INTEGER NULL REFERENCES sequence_variant(id)",
        # 2026-05-24: custom sequence mode for personalized sequences (wait_for_all | asap)
        "ALTER TABLE campaign ADD COLUMN IF NOT EXISTS custom_sequence_mode VARCHAR(32) NOT NULL DEFAULT 'wait_for_all'",
        # 2026-05-24: notification table for in-app notification center
        """
        CREATE TABLE IF NOT EXISTS notification (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            event_type VARCHAR(64) NOT NULL,
            title VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            data_json JSONB DEFAULT '{}',
            lead_id INTEGER REFERENCES lead(id) ON DELETE SET NULL,
            campaign_id INTEGER REFERENCES campaign(id) ON DELETE SET NULL,
            inbox_id INTEGER REFERENCES inbox(id) ON DELETE SET NULL,
            read_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_notification_user_created ON notification (user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_notification_user_read ON notification (user_id, read_at)",
        "CREATE INDEX IF NOT EXISTS ix_notification_event ON notification (event_type)",
        # 2026-09-04: generic SMTP / IMAP provider (per-inbox credentials + mirrors)
        """
        CREATE TABLE IF NOT EXISTS smtp_account (
            id SERIAL PRIMARY KEY,
            inbox_id INTEGER NOT NULL UNIQUE REFERENCES inbox(id) ON DELETE CASCADE,
            smtp_host VARCHAR(255) NOT NULL DEFAULT '',
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_username VARCHAR(255) NOT NULL DEFAULT '',
            smtp_password TEXT NOT NULL DEFAULT '',
            smtp_use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            smtp_use_ssl BOOLEAN NOT NULL DEFAULT FALSE,
            imap_host VARCHAR(255) NOT NULL DEFAULT '',
            imap_port INTEGER NOT NULL DEFAULT 993,
            imap_username VARCHAR(255) NOT NULL DEFAULT '',
            imap_password TEXT NOT NULL DEFAULT '',
            imap_use_ssl BOOLEAN NOT NULL DEFAULT TRUE,
            last_tested_at TIMESTAMP WITHOUT TIME ZONE,
            last_test_ok BOOLEAN NOT NULL DEFAULT FALSE,
            last_test_error TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS smtp_sync_state (
            id SERIAL PRIMARY KEY,
            inbox_id INTEGER NOT NULL UNIQUE REFERENCES inbox(id) ON DELETE CASCADE,
            uidvalidity BIGINT,
            last_uid INTEGER NOT NULL DEFAULT 0,
            last_sync_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS smtp_thread (
            inbox_id INTEGER NOT NULL REFERENCES inbox(id) ON DELETE CASCADE,
            thread_key VARCHAR(512) NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            last_received_at TIMESTAMP WITHOUT TIME ZONE,
            is_lead_thread BOOLEAN NOT NULL DEFAULT FALSE,
            unread_lead_reply BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (inbox_id, thread_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS smtp_message (
            inbox_id INTEGER NOT NULL REFERENCES inbox(id) ON DELETE CASCADE,
            message_id VARCHAR(512) NOT NULL,
            thread_key VARCHAR(512) NOT NULL,
            rfc_message_id VARCHAR(512),
            in_reply_to VARCHAR(512),
            received_at TIMESTAMP WITHOUT TIME ZONE,
            subject TEXT NOT NULL DEFAULT '',
            from_address VARCHAR(255) NOT NULL DEFAULT '',
            to_addresses TEXT NOT NULL DEFAULT '',
            body_plain TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            direction VARCHAR(16) NOT NULL DEFAULT 'received',
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (inbox_id, message_id),
            CONSTRAINT fk_smtp_message_thread FOREIGN KEY (inbox_id, thread_key)
                REFERENCES smtp_thread(inbox_id, thread_key) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_smtp_thread_inbox_last_date ON smtp_thread (inbox_id, last_received_at)",
        "CREATE INDEX IF NOT EXISTS ix_smtp_message_inbox_thread_date ON smtp_message (inbox_id, thread_key, received_at)",
        "CREATE INDEX IF NOT EXISTS ix_smtp_message_inbox_received ON smtp_message (inbox_id, received_at)",
        "CREATE INDEX IF NOT EXISTS ix_smtp_message_rfc_id ON smtp_message (rfc_message_id)",
        # 2026-09-22: SMTP diagnose + send observability
        #   last_diagnostic_*: staged diagnostic report (Diagnose button / CLI)
        #   last_send_*:       last real send failure + timestamp (all failures,
        #                      including the previously-swallowed transient ones)
        "ALTER TABLE smtp_account ADD COLUMN IF NOT EXISTS last_diagnostic_at TIMESTAMP WITHOUT TIME ZONE NULL",
        "ALTER TABLE smtp_account ADD COLUMN IF NOT EXISTS last_diagnostic_json TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE smtp_account ADD COLUMN IF NOT EXISTS last_send_error TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE smtp_account ADD COLUMN IF NOT EXISTS last_send_at TIMESTAMP WITHOUT TIME ZONE NULL",
        # 2026-09-22: per-campaign RFC 8058 one-click unsubscribe toggle
        "ALTER TABLE campaign ADD COLUMN IF NOT EXISTS add_one_click_unsubscribe BOOLEAN NOT NULL DEFAULT TRUE",
        # 2026-09-23: exact rendered body sent on each EmailLog.  Lets the Sent
        # view and quoted follow-ups reproduce what was actually sent even when
        # the template uses {{random: ...}} (which cannot be re-derived later).
        "ALTER TABLE email_log ADD COLUMN IF NOT EXISTS body TEXT NULL",
        # Weblinx Outreach OS: Extended Lead fields
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS company VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS phone VARCHAR(64) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS website VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS industry VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS city VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS country VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS lead_source VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS pipeline_status VARCHAR(32) NOT NULL DEFAULT 'new'",
        "ALTER TABLE lead ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'",
        "CREATE INDEX IF NOT EXISTS ix_lead_pipeline_status ON lead (pipeline_status)",
        # Weblinx Outreach OS: Suppression List
        """
        CREATE TABLE IF NOT EXISTS suppression_list (
            id SERIAL PRIMARY KEY,
            email_or_domain VARCHAR(255) NOT NULL UNIQUE,
            reason VARCHAR(128) NOT NULL DEFAULT 'manual',
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_suppression_list_email_or_domain ON suppression_list (email_or_domain)",
        # Weblinx Outreach OS: Email Template Library
        """
        CREATE TABLE IF NOT EXISTS email_template (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            subject VARCHAR(512) NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            is_html BOOLEAN NOT NULL DEFAULT FALSE,
            preview_text VARCHAR(512),
            category VARCHAR(64) NOT NULL DEFAULT 'Cold Outreach',
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        # Weblinx Outreach OS: Import History
        """
        CREATE TABLE IF NOT EXISTS import_history (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            invalid_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
    ]
    # custom_email_override table (IF NOT EXISTS — must be a separate stmt
    # because it uses raw SQL, not ALTER TABLE)
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS custom_email_override (
                id SERIAL PRIMARY KEY,
                campaign_lead_id INTEGER NOT NULL REFERENCES campaign_lead(id) ON DELETE CASCADE,
                sequence_id INTEGER NOT NULL REFERENCES sequence(id) ON DELETE CASCADE,
                subject VARCHAR(512),
                body TEXT,
                is_html BOOLEAN,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                UNIQUE (campaign_lead_id, sequence_id)
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_custom_email_override_cl ON custom_email_override (campaign_lead_id)"
        )
    )
    for stmt in pg_alters:
        await conn.execute(text(stmt))
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ix_inbox_connect_token ON inbox (connect_token)")
    )
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_email ON lead (email)")
    )
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_lead ON campaign_lead (campaign_id, lead_id)")
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS _app_schema_migrations (id VARCHAR(128) PRIMARY KEY)"
        )
    )

    # Backfill enrollment from legacy lead.status + interest.
    # Sync from lead.status must run once only: enrollment is authoritative afterward; API updates cl only.
    once = await conn.execute(
        text(
            """
            INSERT INTO _app_schema_migrations (id)
            VALUES ('20260325_backfill_enrollment_from_lead_legacy_status')
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """
        )
    )
    if once.fetchone() is not None:
        await conn.execute(
            text(
                """
                UPDATE campaign_lead AS cl
                SET enrollment_status = CASE
                    WHEN l.status = 'unsubscribed' THEN 'unsubscribed'
                    WHEN l.status = 'bounced' THEN 'bounced'
                    ELSE cl.enrollment_status
                END
                FROM lead AS l
                WHERE l.id = cl.lead_id
                  AND l.status IN ('unsubscribed', 'bounced')
                """
            )
        )
    await conn.execute(
        text(
            """
            UPDATE campaign_lead
            SET enrollment_status = 'wrong_person',
                interest_status = NULL
            WHERE interest_status = 'wrong_person'
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE campaign_lead
            SET enrollment_status = 'unsubscribed',
                interest_status = NULL
            WHERE interest_status = 'unsubscribed'
            """
        )
    )


async def init_db():
    from app import models  # noqa: F401 - so Base.metadata has all tables
    from app.settings_manager import initialize_settings

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)

    # Load settings from database into memory
    async with AsyncSessionLocal() as session:
        await initialize_settings(session)