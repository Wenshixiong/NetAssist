"""Application version metadata.

Keep the application version in this file only.  The release helper updates
this value and all user-facing components import it from here.
"""

APP_NAME = "NetAssist 网络运维工具"
VERSION = "1.5.0"


def version_text() -> str:
    """Return the display form used by the launcher and web pages."""
    return f"v{VERSION}"
