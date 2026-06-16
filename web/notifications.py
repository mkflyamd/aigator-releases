"""Send Windows Action Center notifications. Gracefully no-ops if plyer unavailable."""


def send_desktop_notification(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title[:64], message=message[:256], app_name="AI Gator", timeout=8)
    except Exception:
        pass
