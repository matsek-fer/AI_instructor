"""Exception hierarchy for the AI-Learner harness."""


class TutorError(Exception):
    """Base class for all AI-Learner errors."""


class LLMError(TutorError):
    """The model call failed or returned something unusable."""


class RefusalError(LLMError):
    """The model (and any configured fallbacks) declined the request."""


class TruncatedOutputError(LLMError):
    """The response hit the max_tokens ceiling before completing."""


class StructuredOutputError(LLMError):
    """The response text could not be parsed against the expected schema."""


class DAGError(TutorError):
    """The concept graph is invalid (cycle, dangling edge, duplicate node)."""


class SessionError(TutorError):
    """Session state could not be loaded or persisted."""
