"""Engagement segmentation engine — pure classification logic.

Classifies users into engagement categories (power, active, light, idle) based
on their aggregated activity metrics and configurable thresholds. All functions
are pure (no I/O) to enable comprehensive property-based testing.
"""

import json
from dataclasses import dataclass
from typing import Literal


@dataclass
class Thresholds:
    """Configurable thresholds for engagement classification.

    Attributes:
        power_messages: Minimum messages to qualify as a power user.
        power_days_active: Minimum days active to qualify as a power user.
        active_messages: Minimum messages to qualify as an active user.
        active_days_active: Minimum days active to qualify as an active user.
        dormant_days_threshold: Days since last activity to classify idle users as dormant.
    """

    power_messages: int = 100
    power_days_active: int = 10
    active_messages: int = 20
    active_days_active: int = 3
    dormant_days_threshold: int = 30


@dataclass
class UserActivity:
    """Aggregated activity metrics for a single user.

    Attributes:
        user_id: Unique user identifier.
        total_messages: Total messages sent within the activity period.
        total_conversations: Total conversations within the activity period.
        days_active: Number of distinct days with recorded activity.
    """

    user_id: str
    total_messages: int
    total_conversations: int
    days_active: int = 0


EngagementCategory = Literal["power", "active", "light", "idle", "dormant"]


def classify_user(activity: UserActivity, thresholds: Thresholds) -> EngagementCategory:
    """Classify a single user into an engagement category.

    Classification uses AND logic: a user must meet BOTH the message count
    AND the days-active threshold to qualify for a category. This prevents
    users with a single burst of activity from being classified as power/active.

    Priority order: power > active > light > idle.

    Args:
        activity: Aggregated activity metrics for the user.
        thresholds: Configuration defining category boundaries.

    Returns:
        The engagement category for the user.
    """
    if (
        activity.total_messages >= thresholds.power_messages
        and activity.days_active >= thresholds.power_days_active
    ):
        return "power"

    if (
        activity.total_messages >= thresholds.active_messages
        and activity.days_active >= thresholds.active_days_active
    ):
        return "active"

    if activity.total_messages >= 1:
        return "light"

    return "idle"


def classify_users(
    activities: list[UserActivity], thresholds: Thresholds
) -> dict[str, EngagementCategory]:
    """Classify all users, returning a mapping of userId to category.

    Args:
        activities: List of aggregated activity metrics for all users.
        thresholds: Configuration defining category boundaries.

    Returns:
        Dict mapping each user_id to its engagement category.
    """
    return {activity.user_id: classify_user(activity, thresholds) for activity in activities}


def validate_thresholds(config: dict) -> tuple[bool, str]:
    """Validate a threshold configuration dictionary.

    Checks that all values are positive integers and that power thresholds
    are strictly greater than active thresholds for both dimensions.

    Args:
        config: Dictionary with expected structure:
            {"power": {"messages": int, "daysActive": int},
             "active": {"messages": int, "daysActive": int}}

    Returns:
        Tuple of (is_valid, error_message). Error message is empty when valid.
    """
    try:
        power = config["power"]
        active = config["active"]

        power_messages = power["messages"]
        power_days_active = power["daysActive"]
        active_messages = active["messages"]
        active_days_active = active["daysActive"]
    except (KeyError, TypeError):
        return False, "Missing required fields: power.messages, power.daysActive, active.messages, active.daysActive"

    values = {
        "power.messages": power_messages,
        "power.daysActive": power_days_active,
        "active.messages": active_messages,
        "active.daysActive": active_days_active,
    }

    for name, value in values.items():
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"{name} must be a positive integer"
        if value <= 0:
            return False, f"{name} must be a positive integer"

    if power_messages <= active_messages:
        return False, "power.messages must be strictly greater than active.messages"

    if power_days_active <= active_days_active:
        return False, "power.daysActive must be strictly greater than active.daysActive"

    # Validate optional dormantDaysThreshold when present
    if "dormantDaysThreshold" in config:
        dormant_threshold = config["dormantDaysThreshold"]
        if not isinstance(dormant_threshold, int) or isinstance(dormant_threshold, bool):
            return False, "dormantDaysThreshold must be a positive integer"
        if dormant_threshold <= 0:
            return False, "dormantDaysThreshold must be a positive integer"

    return True, ""


def reclassify_dormant(
    classifications: dict[str, EngagementCategory],
    frequency_data: dict[str, int | None],  # userId -> daysSinceLastActive (None = no data)
    dormant_days_threshold: int,
) -> dict[str, EngagementCategory]:
    """Reclassify idle users as dormant based on frequency data.

    Pure function — no I/O. Frequency data is passed in as a parameter.
    Users classified as "idle" with daysSinceLastActive >= threshold
    become "dormant". Users with no frequency data remain "idle".

    Args:
        classifications: Mapping of user_id to engagement category.
        frequency_data: Mapping of user_id to days since last active (None = no data).
        dormant_days_threshold: Number of days after which idle users become dormant.

    Returns:
        New dict with updated classifications (idle → dormant where applicable).
    """
    result = dict(classifications)
    for user_id, category in result.items():
        if category == "idle":
            days = frequency_data.get(user_id)
            if days is not None and days >= dormant_days_threshold:
                result[user_id] = "dormant"
    return result


def parse_thresholds(raw_json: str) -> Thresholds:
    """Parse a JSON string into a Thresholds instance.

    Falls back to default thresholds if parsing fails or the parsed
    configuration is invalid. Extracts the optional `dormantDaysThreshold`
    field when present and valid (positive integer); otherwise uses the
    default value of 30.

    Args:
        raw_json: JSON string with threshold configuration.

    Returns:
        Thresholds instance (defaults if parsing or validation fails).
    """
    try:
        config = json.loads(raw_json)
        is_valid, _ = validate_thresholds(config)
        if not is_valid:
            return Thresholds()

        # Extract dormantDaysThreshold with fallback to default
        dormant_days = 30
        raw_dormant = config.get("dormantDaysThreshold")
        if (
            isinstance(raw_dormant, int)
            and not isinstance(raw_dormant, bool)
            and raw_dormant > 0
        ):
            dormant_days = raw_dormant

        return Thresholds(
            power_messages=config["power"]["messages"],
            power_days_active=config["power"]["daysActive"],
            active_messages=config["active"]["messages"],
            active_days_active=config["active"]["daysActive"],
            dormant_days_threshold=dormant_days,
        )
    except (json.JSONDecodeError, TypeError, KeyError):
        return Thresholds()
