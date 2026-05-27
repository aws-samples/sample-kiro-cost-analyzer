"""Normalizer — converts raw CSV records into UserActivityRecord (new format only)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UserActivityRecord:
    """User activity record from Kiro user_report CSV."""

    userId: str
    date: str  # YYYY-MM-DD
    clientType: str  # KIRO_IDE, KIRO_CLI, PLUGIN
    subscriptionTier: str  # PRO, PRO_PLUS, POWER
    profileId: str
    totalMessages: int
    chatConversations: int
    creditsUsed: float
    overageEnabled: bool
    overageCap: float
    overageCreditsUsed: float
    displayName: str = ""
    userName: str = ""
    modelMessages: dict[str, int] = field(default_factory=dict)
    newUser: bool = False


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_bool(value: str, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return default


def normalize_records(
    raw_records: list[dict],
    format_type: str = "new",
    path_metadata: dict | None = None,
) -> list[UserActivityRecord]:
    """Normalize raw CSV dicts into UserActivityRecord instances."""
    results = []
    for raw in raw_records:
        client_type = raw.get("Client_Type", "").strip()
        if not client_type and path_metadata:
            client_type = path_metadata.get("client_type") or ""

        # Extract dynamic model message columns
        model_messages: dict[str, int] = {}
        for col, value in raw.items():
            if col.endswith("_messages") and col != "Total_Messages":
                model_name = col.removesuffix("_messages")
                count = _safe_int(value)
                if count > 0:
                    model_messages[model_name] = count

        # Extract New_User flag
        new_user = _safe_bool(raw.get("New_User", "false"))

        results.append(UserActivityRecord(
            userId=raw.get("UserId", ""),
            date=raw.get("Date", ""),
            clientType=client_type,
            subscriptionTier=raw.get("Subscription_Tier", ""),
            profileId=raw.get("ProfileId", ""),
            totalMessages=_safe_int(raw.get("Total_Messages")),
            chatConversations=_safe_int(raw.get("Chat_Conversations")),
            creditsUsed=_safe_float(raw.get("Credits_Used")),
            overageEnabled=_safe_bool(raw.get("Overage_Enabled")),
            overageCap=_safe_float(raw.get("Overage_Cap")),
            overageCreditsUsed=_safe_float(raw.get("Overage_Credits_Used")),
            modelMessages=model_messages,
            newUser=new_user,
        ))
    return results
