"""Helpers for reading / writing application settings stored in the DB.

All configuration is now stored in the database instead of .env files,
allowing users to manage settings from the frontend interface.
"""
# // BEACON SYNC: This file handles tracking logic that Beacon mirrors.
# // Any changes to tracking behavior, event types, metadata collected, or URL structure
# // must also be reflected in the Beacon service (/beacon or the separate Beacon repo).
# // If you are an AI agent, add a TODO at the end of your response listing what needs to be updated in Beacon.

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.settings_manager import settings

log = logging.getLogger("quickly.app_settings")

# Atomic budget reservation lock across concurrent tasks bound to current event loop
_claim_locks: dict = {}

def get_claim_lock() -> asyncio.Lock:
    """Return an asyncio.Lock bound to the current running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop not in _claim_locks:
        _claim_locks[loop] = asyncio.Lock()
    return _claim_locks[loop]


async def acquire_db_budget_lock(session: AsyncSession) -> None:
    """Acquire a cross-process database-level transaction lock for atomic budget reservation."""
    from sqlalchemy import text, update, select
    import time
    dialect_name = session.bind.dialect.name if session.bind else ""
    if dialect_name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(789123456);"))
    else:
        # SQLite / other SQL DB: touch a dedicated lock row to serialize transactions
        for attempt in range(10):
            try:
                res = await session.execute(
                    update(AppSetting)
                    .where(AppSetting.key == "global_sending_lock")
                    .values(value=str(time.time()))
                )
                if res.rowcount == 0:
                    session.add(AppSetting(key="global_sending_lock", value=str(time.time())))
                    await session.flush()
                break
            except Exception as e:
                if "locked" in str(e).lower() and attempt < 9:
                    await asyncio.sleep(0.05 * (attempt + 1))
                else:
                    raise


# Canonical keys ---------------------------------------------------------------
GOOGLE_CLIENT_ID_KEY = "google_client_id"
GOOGLE_CLIENT_SECRET_KEY = "google_client_secret"
TEST_MODE_KEY = "test_mode"
# Anonymous usage telemetry UI toggle. Enabled by default; the UI or
# QUICKLY_TELEMETRY=false can turn it off (see app/telemetry.py).
TELEMETRY_ENABLED_KEY = "telemetry_enabled"
SCHEDULING_STRATEGY_KEY = "scheduling_strategy"  # "priority" (default) | "round_robin"
# ISO-8601 UTC timestamp; bumped when a global queue recalculation completes successfully.
GLOBAL_RECALC_FINISHED_AT_KEY = "global_recalc_finished_at"
GMAIL_PUSH_TOPIC_KEY = "gmail_push_topic"
GMAIL_PUSH_WEBHOOK_TOKEN_KEY = "gmail_push_webhook_token"
GMAIL_REPLY_SYNC_INTERVAL_MINUTES_KEY = "gmail_reply_sync_interval_minutes"

# custom tracking domain (hostname only, e.g. "mail.yourclient.com")
TRACKING_DOMAIN_KEY = "tracking_domain"

# Email verification
EMAIL_VERIFICATION_API_KEY = "email_verification_api_key"
EMAIL_VERIFICATION_PROVIDER = "email_verification_provider"  # default: mailtester_ninja
EMAIL_VERIFICATION_ENABLED = "email_verification_enabled"

# Custom HTTP verification provider settings
EMAIL_VERIFICATION_CUSTOM_URL = "email_verification_custom_url"
EMAIL_VERIFICATION_CUSTOM_FIELD = "email_verification_custom_field"
EMAIL_VERIFICATION_CUSTOM_VALID_VALUES = "email_verification_custom_valid_values"   # JSON array
EMAIL_VERIFICATION_CUSTOM_INVALID_VALUES = "email_verification_custom_invalid_values"  # JSON array
EMAIL_VERIFICATION_CUSTOM_METHOD = "email_verification_custom_method"  # GET | POST

# Connection test tracking (set to "true" after a successful Test Connection run)
EMAIL_VERIFICATION_CONNECTION_TESTED = "email_verification_connection_tested"
EMAIL_VERIFICATION_LAST_ERROR = "email_verification_last_error"
EMAIL_VERIFICATION_LAST_ERROR_AT = "email_verification_last_error_at"


# Generic helpers --------------------------------------------------------------

async def get_setting(db: AsyncSession, key: str) -> str | None:
    """Return the value for *key*, or ``None`` if not set."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def put_setting(db: AsyncSession, key: str, value: str) -> None:
    """Insert or update *key* with *value*."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.flush()


# Google OAuth convenience -----------------------------------------------------

async def get_google_oauth_credentials(db: AsyncSession | None = None) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` from the environment.

    The values are read from ``app.settings_manager.settings`` which itself
    picks them up from environment variables (or a ``.env`` file) when the
    process starts.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        import os
        cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        sec = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        if cid and sec:
            settings.google_client_id = cid
            settings.google_client_secret = sec
        else:
            try:
                from dotenv import dotenv_values
                env_vals = dotenv_values(".env")
                if env_vals.get("GOOGLE_CLIENT_ID") and env_vals.get("GOOGLE_CLIENT_SECRET"):
                    settings.google_client_id = env_vals["GOOGLE_CLIENT_ID"].strip()
                    settings.google_client_secret = env_vals["GOOGLE_CLIENT_SECRET"].strip()
            except Exception:
                pass
    return settings.google_client_id, settings.google_client_secret


async def save_google_oauth_credentials(db: AsyncSession, client_id: str, client_secret: str) -> None:
    """No-op wrapper retained for backward compatibility.

    The application no longer persists OAuth client credentials to the
    database; they are expected to be configured via environment variables.
    Calling this function will log a warning but otherwise do nothing.
    """
    log.warning("save_google_oauth_credentials called but persistence is disabled; "
                "credentials must be set via environment variables")
    # intentionally do not write anything to the database


# Test mode convenience --------------------------------------------------------

async def get_test_mode(db: AsyncSession) -> bool:
    """Return whether test mode is enabled."""
    value = await get_setting(db, TEST_MODE_KEY)
    return value and value.lower() in ("true", "1", "yes")


async def set_test_mode(db: AsyncSession, enabled: bool) -> None:
    """Enable or disable test mode."""
    await put_setting(db, TEST_MODE_KEY, "true" if enabled else "false")
    await db.flush()
    # Reload settings into memory cache
    from app.settings_manager import reload_settings
    await reload_settings(db)
    log.info("Test mode %s", "enabled" if enabled else "disabled")


# Telemetry convenience --------------------------------------------------------

async def get_telemetry_enabled(db: AsyncSession) -> bool:
    """Return the in-app telemetry toggle (opt-out by default)."""
    value = await get_setting(db, TELEMETRY_ENABLED_KEY)
    if value is None:
        return True
    return value.strip().lower() in ("true", "1", "yes")


async def set_telemetry_enabled(db: AsyncSession, enabled: bool) -> None:
    """Enable or disable anonymous usage telemetry from the settings UI."""
    await put_setting(db, TELEMETRY_ENABLED_KEY, "true" if enabled else "false")
    await db.flush()
    from app.settings_manager import reload_settings
    await reload_settings(db)
    log.info("Telemetry %s", "enabled" if enabled else "disabled")


# Scheduling strategy convenience ---------------------------------------------

VALID_SCHEDULING_STRATEGIES = ("priority", "round_robin")


async def get_scheduling_strategy(db: AsyncSession) -> str:
    """Return the active scheduling strategy ('priority' or 'round_robin')."""
    value = await get_setting(db, SCHEDULING_STRATEGY_KEY)
    if value in VALID_SCHEDULING_STRATEGIES:
        return value
    return "priority"  # default


async def set_scheduling_strategy(db: AsyncSession, strategy: str) -> None:
    """Persist the scheduling strategy ('priority' or 'round_robin')."""
    if strategy not in VALID_SCHEDULING_STRATEGIES:
        raise ValueError(f"Invalid strategy '{strategy}'; must be one of {VALID_SCHEDULING_STRATEGIES}")
    await put_setting(db, SCHEDULING_STRATEGY_KEY, strategy)
    await db.flush()
    log.info("Scheduling strategy set to '%s'", strategy)


# Gmail reply sync / push settings --------------------------------------------

async def get_gmail_sync_config(db: AsyncSession) -> dict:
    """Return Gmail push/poll sync settings."""
    topic = await get_setting(db, GMAIL_PUSH_TOPIC_KEY) or ""
    webhook_token = await get_setting(db, GMAIL_PUSH_WEBHOOK_TOKEN_KEY) or ""
    interval_raw = await get_setting(db, GMAIL_REPLY_SYNC_INTERVAL_MINUTES_KEY) or "5"
    try:
        interval_minutes = max(1, int(interval_raw))
    except Exception:
        interval_minutes = 5
    return {
        "push_topic": topic,
        "push_topic_configured": bool(topic),
        "webhook_token": webhook_token,
        "webhook_token_configured": bool(webhook_token),
        "sync_interval_minutes": interval_minutes,
    }


async def save_gmail_sync_config(
    db: AsyncSession,
    push_topic: str,
    webhook_token: str,
    sync_interval_minutes: int,
) -> None:
    """Persist Gmail push/poll sync settings."""
    await put_setting(db, GMAIL_PUSH_TOPIC_KEY, push_topic.strip())
    await put_setting(db, GMAIL_PUSH_WEBHOOK_TOKEN_KEY, webhook_token.strip())
    await put_setting(db, GMAIL_REPLY_SYNC_INTERVAL_MINUTES_KEY, str(max(1, int(sync_interval_minutes))))
    await db.flush()


# Tracking domain helpers ------------------------------------------------------

async def get_tracking_base_url(db: AsyncSession) -> str:
    """Return the app-level fallback base URL used when an inbox has no custom domain.

    Tracking domains are now per-inbox (``Inbox.tracking_domain``).  This
    function remains for backward-compatibility but no longer queries the DB.
    """
    return settings.base_url.rstrip("/")


def get_inbox_tracking_base(inbox, fallback_base_url: str) -> str:
    """Return the tracking base URL for *inbox*.

    If Beacon is connected (``beacon_connected`` and ``beacon_base_url``), uses
    that origin. Else if ``tracking_domain`` is set, returns
    ``https://<tracking_domain>``. Otherwise falls back to *fallback_base_url*.
    """
    if getattr(inbox, "beacon_connected", False):
        bu = (getattr(inbox, "beacon_base_url", None) or "").strip().rstrip("/")
        if bu:
            return bu
    td = getattr(inbox, "tracking_domain", None)
    if td:
        return f"https://{td}"
    return fallback_base_url.rstrip("/")


# Office 365 OAuth convenience -------------------------------------------------

async def get_office365_oauth_credentials(db: AsyncSession | None = None) -> tuple[str, str, str]:
    """Return ``(client_id, client_secret, tenant_id)`` from environment."""
    return (
        settings.office365_client_id,
        settings.office365_client_secret,
        settings.office365_tenant_id,
    )


# Scheduled / destination backup (PostgreSQL dumps) ---------------------------

BACKUP_SCHEDULE_ENABLED_KEY = "backup_schedule_enabled"
BACKUP_CRON_EXPRESSION_KEY = "backup_cron_expression"
BACKUP_SAVE_LOCAL_KEY = "backup_save_local"
BACKUP_LOCAL_RELATIVE_PATH_KEY = "backup_local_relative_path"
BACKUP_SEND_WEBHOOK_KEY = "backup_send_webhook"
BACKUP_WEBHOOK_URL_KEY = "backup_webhook_url"
BACKUP_WEBHOOK_AUTH_HEADER_KEY = "backup_webhook_auth_header"
BACKUP_ENCRYPT_ENABLED_KEY = "backup_encrypt_enabled"
BACKUP_ENCRYPT_PASSWORD_KEY = "backup_encrypt_password"
BACKUP_ENCRYPT_HINT_KEY = "backup_encrypt_hint"


def _is_truthy_setting(raw: str | None) -> bool:
    return bool(raw and raw.strip().lower() in ("true", "1", "yes"))


async def get_backup_config(db: AsyncSession) -> dict:
    """Return persisted backup schedule and destination flags."""
    from app.backup_pg import normalize_user_backup_path

    cron = (await get_setting(db, BACKUP_CRON_EXPRESSION_KEY) or "").strip()
    local_rel = normalize_user_backup_path(await get_setting(db, BACKUP_LOCAL_RELATIVE_PATH_KEY))
    return {
        "schedule_enabled": _is_truthy_setting(await get_setting(db, BACKUP_SCHEDULE_ENABLED_KEY)),
        "cron_expression": cron,
        "save_local": _is_truthy_setting(await get_setting(db, BACKUP_SAVE_LOCAL_KEY)),
        "local_relative_path": local_rel,
        "send_webhook": _is_truthy_setting(await get_setting(db, BACKUP_SEND_WEBHOOK_KEY)),
        "webhook_url": (await get_setting(db, BACKUP_WEBHOOK_URL_KEY) or "").strip(),
        "webhook_auth_header": (await get_setting(db, BACKUP_WEBHOOK_AUTH_HEADER_KEY) or "").strip(),
        "encrypt_backups": _is_truthy_setting(await get_setting(db, BACKUP_ENCRYPT_ENABLED_KEY)),
        "backup_encryption_password": (await get_setting(db, BACKUP_ENCRYPT_PASSWORD_KEY) or "").strip(),
        "backup_encryption_hint": (await get_setting(db, BACKUP_ENCRYPT_HINT_KEY) or "").strip(),
    }


async def save_backup_config(
    db: AsyncSession,
    *,
    schedule_enabled: bool,
    cron_expression: str,
    save_local: bool,
    local_relative_path: str,
    send_webhook: bool,
    webhook_url: str,
    webhook_auth_header: str,
    encrypt_backups: bool,
    backup_encryption_password: str,
    backup_encryption_hint: str,
) -> None:
    """Persist backup settings (caller commits)."""
    from app.backup_pg import normalize_user_backup_path

    await put_setting(db, BACKUP_SCHEDULE_ENABLED_KEY, "true" if schedule_enabled else "false")
    await put_setting(db, BACKUP_CRON_EXPRESSION_KEY, cron_expression.strip())
    await put_setting(db, BACKUP_SAVE_LOCAL_KEY, "true" if save_local else "false")
    await put_setting(db, BACKUP_LOCAL_RELATIVE_PATH_KEY, normalize_user_backup_path(local_relative_path))
    await put_setting(db, BACKUP_SEND_WEBHOOK_KEY, "true" if send_webhook else "false")
    await put_setting(db, BACKUP_WEBHOOK_URL_KEY, webhook_url.strip())
    await put_setting(db, BACKUP_WEBHOOK_AUTH_HEADER_KEY, webhook_auth_header.strip())
    await put_setting(db, BACKUP_ENCRYPT_ENABLED_KEY, "true" if encrypt_backups else "false")
    await put_setting(db, BACKUP_ENCRYPT_PASSWORD_KEY, backup_encryption_password.strip())
    await put_setting(db, BACKUP_ENCRYPT_HINT_KEY, backup_encryption_hint.strip())
    await db.flush()


# ── Global Monthly Sending Budget Settings ──────────────────────────────────
MONTHLY_SENDING_BUDGET_KEY = "monthly_sending_budget"
BILLING_CYCLE_START_DAY_KEY = "billing_cycle_start_day"


def get_billing_period_bounds(ref_date: Optional[datetime] = None, cycle_start_day: int = 1) -> tuple[datetime, datetime]:
    """Calculate the exact UTC start and end bounds of the current billing cycle.

    Uses actual calendar lengths without assuming 30 days.
    """
    now = ref_date or datetime.now(timezone.utc).replace(tzinfo=None)
    cycle_day = max(1, min(28, cycle_start_day))

    if now.day >= cycle_day:
        start_date = datetime(now.year, now.month, cycle_day, 0, 0, 0)
        if now.month == 12:
            end_date = datetime(now.year + 1, 1, cycle_day, 0, 0, 0)
        else:
            end_date = datetime(now.year, now.month + 1, cycle_day, 0, 0, 0)
    else:
        if now.month == 1:
            start_date = datetime(now.year - 1, 12, cycle_day, 0, 0, 0)
        else:
            start_date = datetime(now.year, now.month - 1, cycle_day, 0, 0, 0)
        end_date = datetime(now.year, now.month, cycle_day, 0, 0, 0)

    return start_date, end_date


async def get_monthly_sending_budget(db: AsyncSession) -> int:
    val = await get_setting(db, MONTHLY_SENDING_BUDGET_KEY)
    if val:
        try:
            return max(0, int(val))
        except ValueError:
            pass
    return 10000  # Default 10,000 emails/month


async def set_monthly_sending_budget(db: AsyncSession, budget: int) -> None:
    await put_setting(db, MONTHLY_SENDING_BUDGET_KEY, str(max(0, int(budget))))


async def get_billing_cycle_start_day(db: AsyncSession) -> int:
    val = await get_setting(db, BILLING_CYCLE_START_DAY_KEY)
    if val:
        try:
            return max(1, min(28, int(val)))
        except ValueError:
            pass
    return 1  # 1st of each month by default


async def set_billing_cycle_start_day(db: AsyncSession, day: int) -> None:
    await put_setting(db, BILLING_CYCLE_START_DAY_KEY, str(max(1, min(28, int(day)))))


async def check_and_reserve_monthly_budget(
    db: AsyncSession,
    additional_units: int = 1,
    current_slot_id: Optional[int] = None,
    current_direct_id: Optional[int] = None,
    ref_date: Optional[datetime] = None,
) -> tuple[bool, int, int]:
    """Check if additional_units can be sent within the active monthly sending budget.

    Takes into account:
    - Successfully sent EmailLog within current billing period
    - Successfully sent DirectEmail within current billing period
    - In-flight QueueSlot ('processing') claimed within the last 5 minutes (excluding current_slot_id)
    - In-flight DirectEmail ('sending') updated within the last 5 minutes (excluding current_direct_id)

    Returns:
        (is_allowed: bool, total_consumed: int, remaining_budget: int)
    """
    from app.models import EmailLog, DirectEmail, QueueSlot

    budget = await get_monthly_sending_budget(db)
    if budget <= 0:
        return True, 0, 0

    now_utc = ref_date or datetime.now(timezone.utc).replace(tzinfo=None)
    cycle_day = await get_billing_cycle_start_day(db)
    start_utc, end_utc = get_billing_period_bounds(ref_date=now_utc, cycle_start_day=cycle_day)
    stale_threshold = now_utc - timedelta(minutes=5)

    # 1. Committed EmailLog
    log_res = await db.execute(
        select(func.count(EmailLog.id)).where(
            EmailLog.sent_at >= start_utc,
            EmailLog.sent_at < end_utc,
        )
    )
    email_logs_sent = log_res.scalar() or 0

    # 2. Committed DirectEmail
    direct_res = await db.execute(
        select(func.count(DirectEmail.id)).where(
            DirectEmail.status == "sent",
            DirectEmail.sent_at >= start_utc,
            DirectEmail.sent_at < end_utc,
        )
    )
    direct_sent = direct_res.scalar() or 0

    # 3. In-flight QueueSlot (status == 'processing' claimed within 5 mins)
    slot_conds = [
        QueueSlot.status == "processing",
        QueueSlot.claimed_at.isnot(None),
        QueueSlot.claimed_at >= stale_threshold,
    ]
    if current_slot_id is not None:
        slot_conds.append(QueueSlot.id != current_slot_id)
    inflight_slots = (await db.execute(select(func.count(QueueSlot.id)).where(*slot_conds))).scalar() or 0

    # 4. In-flight DirectEmail (status == 'sending' updated within 5 mins)
    direct_inflight_conds = [
        DirectEmail.status == "sending",
        DirectEmail.updated_at >= stale_threshold,
    ]
    if current_direct_id is not None:
        direct_inflight_conds.append(DirectEmail.id != current_direct_id)
    inflight_direct = (await db.execute(select(func.count(DirectEmail.id)).where(*direct_inflight_conds))).scalar() or 0

    # 5. Uncertain QueueSlot (status == 'uncertain' in current cycle)
    uncertain_slot_conds = [
        QueueSlot.status == "uncertain",
        func.coalesce(QueueSlot.claimed_at, QueueSlot.scheduled_date) >= start_utc,
        func.coalesce(QueueSlot.claimed_at, QueueSlot.scheduled_date) < end_utc,
    ]
    if current_slot_id is not None:
        uncertain_slot_conds.append(QueueSlot.id != current_slot_id)
    uncertain_slots = (await db.execute(select(func.count(QueueSlot.id)).where(*uncertain_slot_conds))).scalar() or 0

    # 6. Uncertain DirectEmail (status == 'uncertain' in current cycle)
    uncertain_direct_conds = [
        DirectEmail.status == "uncertain",
        func.coalesce(DirectEmail.updated_at, DirectEmail.created_at) >= start_utc,
        func.coalesce(DirectEmail.updated_at, DirectEmail.created_at) < end_utc,
    ]
    if current_direct_id is not None:
        uncertain_direct_conds.append(DirectEmail.id != current_direct_id)
    uncertain_direct = (await db.execute(select(func.count(DirectEmail.id)).where(*uncertain_direct_conds))).scalar() or 0

    total_consumed = email_logs_sent + direct_sent + inflight_slots + inflight_direct + uncertain_slots + uncertain_direct
    is_allowed = (total_consumed + additional_units) <= budget
    remaining = max(0, budget - total_consumed)
    return is_allowed, total_consumed, remaining


async def get_monthly_sending_stats(db: AsyncSession) -> dict:
    """Calculate real-time monthly budget metrics across all campaigns and inboxes."""
    from app.models import EmailLog, DirectEmail, Inbox, QueueSlot

    budget = await get_monthly_sending_budget(db)
    cycle_day = await get_billing_cycle_start_day(db)
    start_utc, end_utc = get_billing_period_bounds(cycle_start_day=cycle_day)

    # Count EmailLog sent in current cycle
    log_res = await db.execute(
        select(func.count(EmailLog.id)).where(
            EmailLog.sent_at >= start_utc,
            EmailLog.sent_at < end_utc,
        )
    )
    email_logs_sent = log_res.scalar() or 0

    # Count DirectEmail sent in current cycle
    direct_res = await db.execute(
        select(func.count(DirectEmail.id)).where(
            DirectEmail.status == "sent",
            DirectEmail.sent_at >= start_utc,
            DirectEmail.sent_at < end_utc,
        )
    )
    direct_sent = direct_res.scalar() or 0

    # Count in-flight operations
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_threshold = now_utc - timedelta(minutes=5)

    inflight_slots_res = await db.execute(
        select(func.count(QueueSlot.id)).where(
            QueueSlot.status == "processing",
            QueueSlot.claimed_at.isnot(None),
            QueueSlot.claimed_at >= stale_threshold,
        )
    )
    inflight_slots = inflight_slots_res.scalar() or 0

    inflight_direct_res = await db.execute(
        select(func.count(DirectEmail.id)).where(
            DirectEmail.status == "sending",
            DirectEmail.updated_at >= stale_threshold,
        )
    )
    inflight_direct = inflight_direct_res.scalar() or 0

    # Count uncertain operations
    uncertain_slots_res = await db.execute(
        select(func.count(QueueSlot.id)).where(
            QueueSlot.status == "uncertain",
            func.coalesce(QueueSlot.claimed_at, QueueSlot.scheduled_date) >= start_utc,
            func.coalesce(QueueSlot.claimed_at, QueueSlot.scheduled_date) < end_utc,
        )
    )
    uncertain_slots = uncertain_slots_res.scalar() or 0

    uncertain_direct_res = await db.execute(
        select(func.count(DirectEmail.id)).where(
            DirectEmail.status == "uncertain",
            func.coalesce(DirectEmail.updated_at, DirectEmail.created_at) >= start_utc,
            func.coalesce(DirectEmail.updated_at, DirectEmail.created_at) < end_utc,
        )
    )
    uncertain_direct = uncertain_direct_res.scalar() or 0
    total_uncertain = uncertain_slots + uncertain_direct

    total_committed = email_logs_sent + direct_sent
    total_in_flight = inflight_slots + inflight_direct
    total_consumed = total_committed + total_in_flight + total_uncertain
    remaining = max(0, budget - total_consumed) if budget > 0 else 0
    usage_pct = round((total_consumed / budget * 100), 2) if budget > 0 else 0.0

    inboxes_res = await db.execute(
        select(Inbox.id, Inbox.email, Inbox.display_name, Inbox.paused, Inbox.provider).where(
            Inbox.paused == False
        )
    )
    active_inboxes = [
        {"id": r[0], "email": r[1], "display_name": r[2] or r[1], "provider": r[4]}
        for r in inboxes_res.all()
    ]

    return {
        "monthly_budget": budget,
        "sent_this_month": total_consumed,
        "committed_sent": total_committed,
        "in_flight": total_in_flight,
        "uncertain_count": total_uncertain,
        "remaining_budget": remaining,
        "usage_percentage": min(100.0, usage_pct),
        "is_exhausted": total_consumed >= budget if budget > 0 else False,
        "billing_period_start": start_utc.isoformat() + "Z",
        "billing_period_end": end_utc.isoformat() + "Z",
        "billing_cycle_start_day": cycle_day,
        "active_inboxes_count": len(active_inboxes),
        "active_inboxes": active_inboxes,
    }

