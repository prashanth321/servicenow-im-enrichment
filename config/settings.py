"""
Application settings loaded from environment variables using pydantic-settings.

All ServiceNow connection parameters, server configuration, and operational
settings are defined here and read from a .env file or environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the ServiceNow IM Enrichment service.

    Attributes:
        sn_base_url: Base URL of the ServiceNow instance (e.g. https://dev12345.service-now.com).
        sn_username: ServiceNow API username with read/write access to incidents and CMDB.
        sn_password: ServiceNow API password (use a dedicated integration account).
        port: Port the FastAPI server listens on.
        polling_interval_seconds: Seconds between polling cycles when running in poll mode.
        log_level: Python log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """

    sn_base_url: str
    sn_username: str
    sn_password: str
    port: int = 3000
    polling_interval_seconds: int = 60
    log_level: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Module-level singleton so all imports share one instance
settings = Settings()
