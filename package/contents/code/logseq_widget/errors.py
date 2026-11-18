"""The error type the helper reports to the widget."""


class HelperError(Exception):
    """An error whose message is shown to the user as-is."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code
