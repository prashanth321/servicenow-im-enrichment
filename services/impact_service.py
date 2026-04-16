"""
Business impact derivation — pure function, no external API calls.

The impact level is inferred from the CI's service tier and criticality
values that were fetched from the CMDB during earlier enrichment steps.
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


def derive_business_impact(
    service_tier: str | None,
    criticality: str | None,
) -> str:
    """Derive a human-readable business impact string.

    Decision matrix:
        * Tier 1 **or** criticality Critical → ``"High"``
        * Tier 2 **or** criticality High     → ``"Medium"``
        * Tier 3 **or** criticality Low      → ``"Low"``
        * Anything else                      → ``"Medium"`` (safe default)

    Args:
        service_tier: The CI's service tier (e.g. ``"1"``, ``"2"``, ``"3"``).
        criticality: The CI's criticality label (e.g. ``"Critical"``, ``"High"``).

    Returns:
        One of ``"High"``, ``"Medium"``, or ``"Low"``.
    """
    tier = (service_tier or "").strip()
    crit = (criticality or "").strip().lower()

    # Tier-1 or critical assets always warrant the highest impact
    if tier == "1" or crit == "critical":
        impact = "High"
    # Tier-2 or high-criticality assets map to medium impact
    elif tier == "2" or crit == "high":
        impact = "Medium"
    # Tier-3 or low-criticality assets map to low impact
    elif tier == "3" or crit == "low":
        impact = "Low"
    else:
        # Default to medium when data is missing or unrecognised
        impact = "Medium"

    logger.info("Derived business impact: %s (tier=%s, criticality=%s)", impact, service_tier, criticality)
    return impact
