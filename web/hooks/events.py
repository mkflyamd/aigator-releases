"""Hook event name constants shared across Gator."""

# Inherited from Claude Code spec
PRE_TOOL_USE = "PreToolUse"
POST_TOOL_USE = "PostToolUse"
BEFORE_AGENT_START = "BeforeAgentStart"
AFTER_AGENT_COMPLETE = "AfterAgentComplete"
ON_ERROR = "OnError"
ON_FILE_CHANGE = "OnFileChange"

# Gator-specific events
BEFORE_EMAIL_SEND = "BeforeEmailSend"
BEFORE_TEAMS_MESSAGE = "BeforeTeamsMessage"
BEFORE_SLACK_MESSAGE = "BeforeSlackMessage"
AFTER_MODEL_TRAIN_RUN = "AfterModelTrainRun"
