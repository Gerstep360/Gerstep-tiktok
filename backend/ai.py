"""Private admin-only AI, with no dependency on the desktop or TikTok SDK."""
try:
    from ai_common.config import AIConfig
    from ai_common.preview import PreviewChat
except ModuleNotFoundError:
    from vps.ai_common.config import AIConfig
    from vps.ai_common.preview import PreviewChat


def create_preview():
    try:
        config = AIConfig.from_env()
    except ValueError:
        config = AIConfig(enabled=False)
    return PreviewChat(config)
