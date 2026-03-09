APP_NAME = "Gridoryn"
APP_VERSION = "2.0.0"
APP_PROFILE = "default"
APP_LOG_SLUG = "gridoryn"
APP_STORAGE_ORGANIZATION = "Gridoryn"
APP_STORAGE_NAME = "Gridoryn"


def app_display_name() -> str:
    return APP_NAME


def app_display_version() -> str:
    return f"v{APP_VERSION}"


def app_storage_identity() -> tuple[str, str]:
    return APP_STORAGE_ORGANIZATION, APP_STORAGE_NAME
