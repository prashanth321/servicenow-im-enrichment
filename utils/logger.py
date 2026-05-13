"""
Structured JSON logging setup using python-json-logger.

Provides a factory function that returns a ``logging.LoggerAdapter`` which
automatically injects ``incident_number`` into every log record so that log
lines can be correlated to a specific ServiceNow incident.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

from config.settings import settings


def _build_handler() -> logging.StreamHandler:
    """Create a stream handler that writes JSON-formatted log lines to stdout."""
    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)
    return handler


# Shared handler so we don't duplicate output across loggers
_handler = _build_handler()


def get_logger(
    name: str,
    incident_number: str = "N/A",
) -> logging.LoggerAdapter:
    """Return a JSON-structured logger that includes ``incident_number`` in every record.

    Args:
        name: Logger name — typically ``__name__`` of the calling module.
        incident_number: The ServiceNow incident number to tag on each message.

    Returns:
        A ``logging.LoggerAdapter`` pre-configured with the incident context.
    """
    logger = logging.getLogger(name)
    logger.setLevel(settings.log_level.upper())

    # Avoid adding duplicate handlers on repeated calls
    if not logger.handlers:
        logger.addHandler(_handler)
        logger.propagate = False

    return logging.LoggerAdapter(logger, {"incident_number": incident_number})


class _CorrelationAdapter(logging.LoggerAdapter):
    """LoggerAdapter that auto-injects the current request correlation ID."""

    def process(self, msg, kwargs):
        from utils.correlation import get_correlation_id

        extra = {**self.extra, "correlation_id": get_correlation_id()}
        return msg, {**kwargs, "extra": extra}


def get_request_logger(
    name: str,
    incident_number: str = "N/A",
) -> logging.LoggerAdapter:
    """Like :func:`get_logger` but also includes ``correlation_id``."""
    logger = logging.getLogger(name)
    logger.setLevel(settings.log_level.upper())
    if not logger.handlers:
        logger.addHandler(_handler)
        logger.propagate = False
    return _CorrelationAdapter(logger, {"incident_number": incident_number})
