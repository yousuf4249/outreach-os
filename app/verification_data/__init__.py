"""Email verification static dataset package."""
from app.verification_data.loader import (
    is_disposable_domain,
    check_role_account,
    check_typo_suggestion,
    load_disposable_domains,
)

__all__ = [
    "is_disposable_domain",
    "check_role_account",
    "check_typo_suggestion",
    "load_disposable_domains",
]
