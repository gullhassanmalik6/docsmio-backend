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
    PLAN_FREE: ["browser_tools", "local_downloads", "account_history"],
    PLAN_PRO: ["browser_tools", "local_downloads", "account_history", "extended_history"],
    PLAN_BUSINESS: ["browser_tools", "local_downloads", "account_history", "extended_history", "highest_history"],
}


def history_limit(plan: str) -> int:
    return HISTORY_LIMITS.get(plan, HISTORY_LIMITS[PLAN_FREE])


def features_for(plan: str) -> list[str]:
    return list(PLAN_FEATURES.get(plan, PLAN_FEATURES[PLAN_FREE]))
