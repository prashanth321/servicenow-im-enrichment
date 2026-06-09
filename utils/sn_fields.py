"""
Canonical helpers for extracting values from ServiceNow record fields.

ServiceNow REST API returns linked/reference fields as either a plain string
or a ``{"value": "...", "display_value": "..."}`` dict depending on
``sysparm_display_value``.  These helpers normalise both cases.
"""

from __future__ import annotations


def extract_value(field: object) -> str | None:
    """Return the raw *value* of a ServiceNow field, or ``None``.

    Prefers ``value`` over ``display_value`` when the field is a dict.
    """
    if isinstance(field, dict):
        return field.get("value") or None
    if isinstance(field, str) and field.strip():
        return field.strip()
    return None


def extract_display(field: object) -> str | None:
    """Return the *display_value* of a ServiceNow field, or ``None``.

    Prefers ``display_value`` over ``value`` when the field is a dict.
    """
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or None
    if isinstance(field, str) and field.strip():
        return field.strip()
    return None


def extract_display_str(field: object) -> str:
    """Like :func:`extract_display` but always returns ``str`` (never None)."""
    return extract_display(field) or ""


def extract_value_str(field: object) -> str:
    """Like :func:`extract_value` but always returns ``str`` (never None)."""
    return extract_value(field) or ""
