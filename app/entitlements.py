PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_BUSINESS = "business"
PLANS = (PLAN_FREE, PLAN_PRO, PLAN_BUSINESS)

HISTORY_LIMITS = {
    PLAN_FREE: 20,
    PLAN_PRO: 200,
    PLAN_BUSINESS: 1000,
}

PLAN_FEATURES = {
    PLAN_FREE: ["browser_tools", "local_downloads", "account_history", "document_wallet"],
    PLAN_PRO: ["browser_tools", "local_downloads", "account_history", "document_wallet", "extended_history"],
    PLAN_BUSINESS: ["browser_tools", "local_downloads", "account_history", "document_wallet", "extended_history", "highest_history"],
}

STORAGE_QUOTAS = {
    PLAN_FREE: 100 * 1024 * 1024,
    PLAN_PRO: 5 * 1024 * 1024 * 1024,
    PLAN_BUSINESS: 20 * 1024 * 1024 * 1024,
}


def history_limit(plan: str) -> int:
    return HISTORY_LIMITS.get(plan, HISTORY_LIMITS[PLAN_FREE])


def features_for(plan: str) -> list[str]:
    return list(PLAN_FEATURES.get(plan, PLAN_FEATURES[PLAN_FREE]))


def storage_quota(plan: str) -> int:
    return STORAGE_QUOTAS.get(plan, STORAGE_QUOTAS[PLAN_FREE])
