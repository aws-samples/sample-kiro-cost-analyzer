"""Property-based tests for the segmentation engine.

Uses Hypothesis to validate correctness properties of the classification logic.
Classification uses AND logic: messages AND days_active must both meet thresholds.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.handlers.segmentation_engine import (
    EngagementCategory,
    Thresholds,
    UserActivity,
    classify_user,
    validate_thresholds,
)


# Strategy: generate valid Thresholds where power > active > 0 for both dimensions
@st.composite
def valid_thresholds(draw):
    active_messages = draw(st.integers(min_value=1, max_value=5000))
    power_messages = draw(st.integers(min_value=active_messages + 1, max_value=10000))
    active_days_active = draw(st.integers(min_value=1, max_value=100))
    power_days_active = draw(st.integers(min_value=active_days_active + 1, max_value=200))
    return Thresholds(
        power_messages=power_messages,
        power_days_active=power_days_active,
        active_messages=active_messages,
        active_days_active=active_days_active,
    )


# Feature: user-engagement-segmentation, Property 1: Classification completeness and mutual exclusivity
class TestClassificationCompletenessAndMutualExclusivity:
    """Property 1: Classification completeness and mutual exclusivity.

    For any non-negative (messages, days_active) pair and any valid thresholds,
    classify_user assigns exactly one engagement category from
    {power, active, light, idle}, following the priority order
    power > active > light > idle.

    Uses AND logic: both messages AND days_active must meet thresholds.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    """

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_exactly_one_category_returned(self, messages, days_active, thresholds):
        """Every input combination produces exactly one valid category."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )
        result = classify_user(activity, thresholds)

        valid_categories: set[EngagementCategory] = {"power", "active", "light", "idle"}
        assert result in valid_categories

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_priority_order_power(self, messages, days_active, thresholds):
        """If messages >= power_messages AND days_active >= power_days_active, user is power."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )
        result = classify_user(activity, thresholds)

        if messages >= thresholds.power_messages and days_active >= thresholds.power_days_active:
            assert result == "power"

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_priority_order_active(self, messages, days_active, thresholds):
        """If meets active thresholds but not power, user is active."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )
        result = classify_user(activity, thresholds)

        meets_power = (
            messages >= thresholds.power_messages
            and days_active >= thresholds.power_days_active
        )
        meets_active = (
            messages >= thresholds.active_messages
            and days_active >= thresholds.active_days_active
        )

        if meets_active and not meets_power:
            assert result == "active"

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_priority_order_light(self, messages, days_active, thresholds):
        """If messages >= 1 but doesn't meet active thresholds, user is light."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )
        result = classify_user(activity, thresholds)

        meets_active = (
            messages >= thresholds.active_messages
            and days_active >= thresholds.active_days_active
        )

        if messages >= 1 and not meets_active:
            assert result == "light"

    @settings(max_examples=20)
    @given(
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_idle_when_zero_messages(self, days_active, thresholds):
        """A user with zero messages is always idle regardless of days_active."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=0,
            total_conversations=0,
            days_active=days_active,
        )
        result = classify_user(activity, thresholds)
        assert result == "idle"

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=100, max_value=10000),
        thresholds=valid_thresholds(),
    )
    def test_high_messages_low_days_not_power(self, messages, thresholds):
        """A user with many messages but few days active should NOT be power.

        This is the key property that prevents burst users (like amandaqt)
        from being classified as power users.
        """
        activity = UserActivity(
            user_id="burst-user",
            total_messages=messages,
            total_conversations=0,
            days_active=1,  # Only 1 day of activity
        )
        result = classify_user(activity, thresholds)

        # With only 1 day active, should never be power (power requires > 1 day)
        assert result != "power"


# Feature: user-engagement-segmentation, Property 2: Threshold validation correctness
class TestThresholdValidationCorrectness:
    """Property 2: Threshold validation correctness.

    For any threshold configuration dictionary, validate_thresholds SHALL return
    (True, "") if and only if all values are positive integers AND
    power.messages > active.messages AND power.daysActive > active.daysActive.
    For all other inputs, it SHALL return (False, non_empty_error_message).

    **Validates: Requirements 2.5, 2.6**
    """

    @settings(max_examples=20)
    @given(
        power_messages=st.integers(min_value=1, max_value=10000),
        active_messages=st.integers(min_value=1, max_value=10000),
        power_days_active=st.integers(min_value=1, max_value=365),
        active_days_active=st.integers(min_value=1, max_value=365),
    )
    def test_valid_config_returns_true_iff_power_gt_active(
        self, power_messages, active_messages, power_days_active, active_days_active
    ):
        """A config with positive integers returns (True, "") iff power > active for both dims."""
        config = {
            "power": {"messages": power_messages, "daysActive": power_days_active},
            "active": {"messages": active_messages, "daysActive": active_days_active},
        }
        is_valid, error = validate_thresholds(config)

        if power_messages > active_messages and power_days_active > active_days_active:
            assert is_valid is True
            assert error == ""
        else:
            assert is_valid is False
            assert error != ""

    @settings(max_examples=20)
    @given(
        power_messages=st.integers(min_value=-1000, max_value=10000),
        active_messages=st.integers(min_value=-1000, max_value=10000),
        power_days_active=st.integers(min_value=-100, max_value=365),
        active_days_active=st.integers(min_value=-100, max_value=365),
    )
    def test_negative_or_zero_values_fail(
        self, power_messages, active_messages, power_days_active, active_days_active
    ):
        """Any config with negative or zero values returns (False, non-empty error)."""
        config = {
            "power": {"messages": power_messages, "daysActive": power_days_active},
            "active": {"messages": active_messages, "daysActive": active_days_active},
        }
        is_valid, error = validate_thresholds(config)

        has_non_positive = (
            power_messages <= 0
            or active_messages <= 0
            or power_days_active <= 0
            or active_days_active <= 0
        )

        if has_non_positive:
            assert is_valid is False
            assert error != ""

    @settings(max_examples=20)
    @given(data=st.one_of(st.none(), st.text(), st.integers(), st.lists(st.integers())))
    def test_missing_structure_fails(self, data):
        """Configs missing required structure always fail with non-empty error."""
        is_valid, error = validate_thresholds(data if data is not None else {})
        assert is_valid is False
        assert error != ""


# Feature: user-engagement-segmentation, Property 6: Classification is deterministic and threshold-monotonic
class TestClassificationDeterminismAndThresholdMonotonicity:
    """Property 6: Classification is deterministic and threshold-monotonic.

    For any user activity and any two valid threshold configurations T1 and T2
    where T1 is lenient (lower thresholds) and T2 is strict (higher thresholds),
    a user classified as "power" under T2 SHALL also be classified as "power"
    under T1 (lowering thresholds never demotes users).

    **Validates: Requirements 1.1, 2.5**
    """

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        t1_active_messages=st.integers(min_value=1, max_value=2000),
        t1_active_days=st.integers(min_value=1, max_value=50),
        t1_power_msg_offset=st.integers(min_value=1, max_value=3000),
        t1_power_days_offset=st.integers(min_value=1, max_value=100),
        t2_power_msg_extra=st.integers(min_value=0, max_value=5000),
        t2_power_days_extra=st.integers(min_value=0, max_value=100),
    )
    def test_power_under_strict_implies_power_under_lenient(
        self,
        messages,
        days_active,
        t1_active_messages,
        t1_active_days,
        t1_power_msg_offset,
        t1_power_days_offset,
        t2_power_msg_extra,
        t2_power_days_extra,
    ):
        """If a user is 'power' under strict thresholds T2, they are also 'power' under lenient T1."""
        t1_power_messages = t1_active_messages + t1_power_msg_offset
        t1_power_days = t1_active_days + t1_power_days_offset
        t2_power_messages = t1_power_messages + t2_power_msg_extra
        t2_power_days = t1_power_days + t2_power_days_extra
        # T2 active must be < T2 power and > 0
        t2_active_messages = min(t1_active_messages, t2_power_messages - 1)
        t2_active_days = min(t1_active_days, t2_power_days - 1)

        t1 = Thresholds(
            power_messages=t1_power_messages,
            power_days_active=t1_power_days,
            active_messages=t1_active_messages,
            active_days_active=t1_active_days,
        )
        t2 = Thresholds(
            power_messages=t2_power_messages,
            power_days_active=t2_power_days,
            active_messages=t2_active_messages,
            active_days_active=t2_active_days,
        )

        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )

        result_strict = classify_user(activity, t2)
        result_lenient = classify_user(activity, t1)

        if result_strict == "power":
            assert result_lenient == "power"

    @settings(max_examples=20)
    @given(
        messages=st.integers(min_value=0, max_value=10000),
        days_active=st.integers(min_value=0, max_value=365),
        thresholds=valid_thresholds(),
    )
    def test_classification_is_deterministic(self, messages, days_active, thresholds):
        """Classifying the same user with the same thresholds always yields the same result."""
        activity = UserActivity(
            user_id="test-user",
            total_messages=messages,
            total_conversations=0,
            days_active=days_active,
        )

        result1 = classify_user(activity, thresholds)
        result2 = classify_user(activity, thresholds)

        assert result1 == result2
