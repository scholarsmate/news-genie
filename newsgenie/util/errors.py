class NewsGenieError(Exception):
    """Base error for app-level failures."""


class ToolError(NewsGenieError):
    """Tool execution failed (API, parsing, timeout, etc.)."""


class ConfigurationError(NewsGenieError):
    """Missing/invalid configuration."""
