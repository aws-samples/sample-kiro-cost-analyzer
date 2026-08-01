"""Property-based tests for the funnel calculator.

Uses Hypothesis to validate correctness properties of the funnel computation
and derived metrics logic. The funnel has 4 stages (conversations removed).
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from backend.handlers.funnel_calculator import compute_funnel, compute_derived_metrics, FunnelStage
from backend.handlers.segmentation_engine import classify_users, UserActivity, Thresholds, EngagementCategory


# Strategy: generate valid Thresholds where power > active > 0
@st.composite
def valid_thresholds(draw):
    active_messages = draw(st.integers(min_value=1, max_value=5000))
    power_messages = draw(st.integers(min_value=active_messages + 1, max_value=10000))
    return Thresholds(
        power_messages=power_messages,
        active_messages=active_messages,
    )


# Strategy: generate a list of UserActivity items and classify them
@st.composite
def activities_with_classifications(draw, min_size=0, max_size=200):
    """Generate a list of UserActivity and their classifications using real segmentation logic."""
    thresholds = draw(valid_thresholds())
    num_users = draw(st.integers(min_value=min_size, max_value=max_size))
    activities = []
    for i in range(num_users):
        messages = draw(st.integers(min_value=0, max_value=10000))
        activities.append(
            UserActivity(
                user_id=f"user-{i}",
                total_messages=messages,
                total_conversations=0,
            )
        )
    classifications = classify_users(activities, thresholds)
    return activities, classifications


# Feature: user-engagement-segmentation, Property 3: Funnel stage counts are consistent with classifications
class TestFunnelStageCountConsistency:
    """Property 3: Funnel stage counts are consistent with classifications.

    For any list of user activities and their classifications, the funnel
    computed by compute_funnel SHALL produce exactly 4 stages where:
    - allUsers.count == total number of users
    - sentMessages.count == number of users with messages > 0
    - activeUsers.count == number of users classified as "active" or "power"
    - powerUsers.count == number of users classified as "power"

    And each stage count is <= the previous stage count (monotonically non-increasing).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
    """

    @settings(max_examples=20)
    @given(data=activities_with_classifications())
    def test_produces_exactly_four_stages(self, data):
        """compute_funnel always produces exactly 4 stages."""
        activities, classifications = data
        funnel = compute_funnel(activities, classifications)

        assert len(funnel) == 4

    @settings(max_examples=20)
    @given(data=activities_with_classifications())
    def test_stage_counts_match_definitions(self, data):
        """Each stage count matches its expected definition."""
        activities, classifications = data
        funnel = compute_funnel(activities, classifications)

        # Stage 1: allUsers == total number of users
        assert funnel[0].name == "allUsers"
        assert funnel[0].count == len(activities)

        # Stage 2: sentMessages == users with messages > 0
        expected_sent = sum(1 for a in activities if a.total_messages > 0)
        assert funnel[1].name == "sentMessages"
        assert funnel[1].count == expected_sent

        # Stage 3: activeUsers == classified as "active" or "power"
        expected_active = sum(
            1 for cat in classifications.values() if cat in ("active", "power")
        )
        assert funnel[2].name == "activeUsers"
        assert funnel[2].count == expected_active

        # Stage 4: powerUsers == classified as "power"
        expected_power = sum(1 for cat in classifications.values() if cat == "power")
        assert funnel[3].name == "powerUsers"
        assert funnel[3].count == expected_power

    @settings(max_examples=20)
    @given(data=activities_with_classifications())
    def test_stage_counts_monotonically_non_increasing(self, data):
        """Each stage count is <= the previous stage count."""
        activities, classifications = data
        funnel = compute_funnel(activities, classifications)

        for i in range(1, len(funnel)):
            assert funnel[i].count <= funnel[i - 1].count, (
                f"Stage {funnel[i].name} (count={funnel[i].count}) > "
                f"previous stage {funnel[i-1].name} (count={funnel[i-1].count})"
            )


# Feature: user-engagement-segmentation, Property 4: Funnel conversion rates are mathematically correct
class TestFunnelConversionRateCorrectness:
    """Property 4: Funnel conversion rates are mathematically correct.

    For any computed funnel, each stage's conversion rate equals
    (count / prev_count) * 100 or 0.0 when prev is 0.
    The first stage conversion rate is always 100.0.

    **Validates: Requirements 3.7, 3.8**
    """

    @settings(max_examples=20)
    @given(data=activities_with_classifications())
    def test_first_stage_conversion_rate_is_100(self, data):
        """The first stage always has conversion rate 100.0."""
        activities, classifications = data
        funnel = compute_funnel(activities, classifications)

        assert funnel[0].conversion_rate == 100.0

    @settings(max_examples=20)
    @given(data=activities_with_classifications())
    def test_conversion_rates_mathematically_correct(self, data):
        """Each stage's conversion rate equals (count / prev_count) * 100 or 0.0 when prev is 0."""
        activities, classifications = data
        funnel = compute_funnel(activities, classifications)

        for i in range(1, len(funnel)):
            prev_count = funnel[i - 1].count
            current_count = funnel[i].count

            if prev_count == 0:
                expected_rate = 0.0
            else:
                expected_rate = (current_count / prev_count) * 100

            assert funnel[i].conversion_rate == expected_rate, (
                f"Stage {funnel[i].name}: expected conversion_rate={expected_rate}, "
                f"got {funnel[i].conversion_rate} "
                f"(count={current_count}, prev_count={prev_count})"
            )


# Feature: user-engagement-segmentation, Property 5: Derived metrics are consistent with segmentation
class TestDerivedMetricsConsistency:
    """Property 5: Derived metrics are consistent with segmentation.

    For any set of classified users where total_users > 0, the derived metrics
    SHALL satisfy:
    - powerUserPercentage + idleRate <= 100.0
    - activationRate + idleRate == 100.0 (within floating point tolerance)
    - Each metric is rounded to 1 decimal place

    **Validates: Requirements 4.4, 7.1, 7.2, 7.3**
    """

    @settings(max_examples=20)
    @given(data=activities_with_classifications(min_size=1))
    def test_power_plus_idle_lte_100(self, data):
        """powerUserPercentage + idleRate <= 100.0."""
        activities, classifications = data
        total_users = len(activities)
        assume(total_users > 0)

        metrics = compute_derived_metrics(total_users, classifications)

        assert metrics["powerUserPercentage"] + metrics["idleRate"] <= 100.0 + 1e-9

    @settings(max_examples=20)
    @given(data=activities_with_classifications(min_size=1))
    def test_activation_plus_idle_equals_100(self, data):
        """activationRate + idleRate == 100.0 (within floating point tolerance)."""
        activities, classifications = data
        total_users = len(activities)
        assume(total_users > 0)

        metrics = compute_derived_metrics(total_users, classifications)

        total = metrics["activationRate"] + metrics["idleRate"]
        assert abs(total - 100.0) < 0.2, (
            f"activationRate ({metrics['activationRate']}) + "
            f"idleRate ({metrics['idleRate']}) = {total}, expected ~100.0"
        )

    @settings(max_examples=20)
    @given(data=activities_with_classifications(min_size=1))
    def test_metrics_rounded_to_one_decimal(self, data):
        """Each metric is rounded to 1 decimal place."""
        activities, classifications = data
        total_users = len(activities)
        assume(total_users > 0)

        metrics = compute_derived_metrics(total_users, classifications)

        for key in ("powerUserPercentage", "activationRate", "idleRate"):
            value = metrics[key]
            assert abs(value * 10 - round(value * 10)) < 1e-9, (
                f"{key}={value} is not rounded to 1 decimal place"
            )
