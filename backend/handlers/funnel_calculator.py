"""Engagement funnel calculator — pure computation logic.

Computes engagement funnel stages and derived health metrics from classified
user activity data. All functions are pure (no I/O) to enable comprehensive
property-based testing.
"""

from dataclasses import dataclass

try:
    from handlers.segmentation_engine import UserActivity, EngagementCategory
except ImportError:
    from backend.handlers.segmentation_engine import UserActivity, EngagementCategory


@dataclass
class FunnelStage:
    """A single stage in the engagement funnel.

    Attributes:
        name: Identifier for the funnel stage.
        count: Number of users in this stage.
        conversion_rate: Percentage relative to the previous stage.
    """

    name: str
    count: int
    conversion_rate: float


def compute_funnel(
    activities: list[UserActivity],
    classifications: dict[str, EngagementCategory],
) -> list[FunnelStage]:
    """Compute the engagement funnel stages.

    Stages (in order):
    1. allUsers — total count of users
    2. sentMessages — users with messages > 0
    3. activeUsers — classified as 'active' or 'power'
    4. powerUsers — classified as 'power'

    Conversion rate for stage N = (count_N / count_N-1) * 100.
    If count_N-1 is 0, conversion rate is 0.0.
    The first stage always has conversion rate 100.0.

    Args:
        activities: List of aggregated activity metrics for all users.
        classifications: Mapping of user_id to engagement category.

    Returns:
        List of 4 FunnelStage instances in order.
    """
    total_users = len(activities)
    sent_messages = sum(1 for a in activities if a.total_messages > 0)
    active_users = sum(
        1 for cat in classifications.values() if cat in ("active", "power")
    )
    power_users = sum(1 for cat in classifications.values() if cat == "power")

    counts = [total_users, sent_messages, active_users, power_users]
    names = [
        "allUsers",
        "sentMessages",
        "activeUsers",
        "powerUsers",
    ]

    stages: list[FunnelStage] = []
    for i, (name, count) in enumerate(zip(names, counts)):
        if i == 0:
            conversion_rate = 100.0
        else:
            prev_count = counts[i - 1]
            if prev_count == 0:
                conversion_rate = 0.0
            else:
                conversion_rate = (count / prev_count) * 100
        stages.append(FunnelStage(name=name, count=count, conversion_rate=conversion_rate))

    return stages


def compute_derived_metrics(
    total_users: int,
    classifications: dict[str, EngagementCategory],
) -> dict:
    """Compute derived engagement health metrics.

    Args:
        total_users: Total number of users in the activity period.
        classifications: Mapping of user_id to engagement category.

    Returns:
        Dict with keys:
            powerUserPercentage: Percentage of power users (1 decimal place).
            activationRate: Percentage of users who sent at least 1 message
                (i.e., non-idle and non-dormant users) (1 decimal place).
            idleRate: Percentage of idle users (1 decimal place).
            dormantRate: Percentage of dormant users (1 decimal place).
            churnRiskRate: Percentage of idle + dormant users (1 decimal place).
    """
    if total_users == 0:
        return {
            "powerUserPercentage": 0.0,
            "activationRate": 0.0,
            "idleRate": 0.0,
            "dormantRate": 0.0,
            "churnRiskRate": 0.0,
            "idleCount": 0,
            "dormantCount": 0,
            "totalUsers": 0,
        }

    power_count = sum(1 for cat in classifications.values() if cat == "power")
    idle_count = sum(1 for cat in classifications.values() if cat == "idle")
    dormant_count = sum(1 for cat in classifications.values() if cat == "dormant")
    non_idle_count = total_users - idle_count - dormant_count

    power_user_percentage = round((power_count / total_users) * 100, 1)
    activation_rate = round((non_idle_count / total_users) * 100, 1)
    idle_rate = round((idle_count / total_users) * 100, 1)
    dormant_rate = round((dormant_count / total_users) * 100, 1)
    churn_risk_rate = round(((idle_count + dormant_count) / total_users) * 100, 1)

    return {
        "powerUserPercentage": power_user_percentage,
        "activationRate": activation_rate,
        "idleRate": idle_rate,
        "dormantRate": dormant_rate,
        "churnRiskRate": churn_risk_rate,
        # Raw counts give the churn-risk percentage interpretable context
        # in small populations (issue #24 / design critique F9).
        "idleCount": idle_count,
        "dormantCount": dormant_count,
        "totalUsers": total_users,
    }
