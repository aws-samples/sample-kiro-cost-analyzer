from dataclasses import dataclass


@dataclass
class PromptMetadata:
    userId: str
    timestamp: str
    requestId: str
    modelId: str
    triggerType: str
    promptLength: int
    responseLength: int
    displayName: str = ""
    userName: str = ""
    originalUserId: str = ""
    date: str = ""
    hour: str = ""
    region: str = ""
    accountId: str = ""
    conversationId: str = ""
    utteranceId: str = ""
    customizationArn: str = ""
    contentInS3: bool = False
    prompt: str | None = None
    response: str | None = None


@dataclass
class DailyStats:
    date: str
    totalCredits: float
    overageCredits: float
    totalMessages: int
    totalConversations: int
    totalInteractions: int


@dataclass
class ModelDistribution:
    modelId: str
    normalizedModelId: str
    count: int


@dataclass
class TriggerDistribution:
    triggerType: str
    normalizedTriggerType: str
    count: int


@dataclass
class GlobalDailyStats:
    date: str
    totalCredits: float
    overageCredits: float
    totalMessages: int
    totalConversations: int
    totalUsers: int


@dataclass
class TaskEvent:
    bucket: str
    key: str
    fileType: str
    correlationId: str


@dataclass
class TaskResult:
    status: str
    key: str
    recordCount: int
    itemsWritten: int
    durationMs: int
    errorMessage: str = ""
