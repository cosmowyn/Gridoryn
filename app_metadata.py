APP_NAME = "CustomToDo"
APP_VERSION = "1.0.0"
APP_PROFILE = "default"
APP_LOG_SLUG = "customtodo"

# Keep legacy Qt storage identifiers so existing local data continues to load
# from the same per-user directories after the branding cleanup.
APP_STORAGE_ORGANIZATION = "FocusTools"
APP_STORAGE_NAME = "CustomTaskManager"


def app_display_name() -> str:
    return APP_NAME


def app_display_version() -> str:
    return f"v{APP_VERSION}"


def app_storage_identity() -> tuple[str, str]:
    return APP_STORAGE_ORGANIZATION, APP_STORAGE_NAME
