"""
Custom exception classes for the ServiceNow enrichment pipeline.

Using specific exceptions allows callers to distinguish between different
failure modes and apply the correct recovery strategy (e.g. partial
enrichment vs. full abort).
"""


class ServiceNowAPIError(Exception):
    """Raised when a ServiceNow REST API call fails after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class CINotFoundError(Exception):
    """Raised when the requested Configuration Item does not exist in CMDB."""


class OnCallFetchError(Exception):
    """Raised when the on-call rota API call fails or returns unexpected data."""
