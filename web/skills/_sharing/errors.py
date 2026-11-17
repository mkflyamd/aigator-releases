class ShareError(Exception):
    """A sharing failure the user can act on. ``code`` is a short stable slug."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
