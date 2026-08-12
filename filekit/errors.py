"""Error types for filekit."""


class FileKitError(Exception):
    """Raised for any recoverable failure in a filekit operation.

    Every public function raises this (and only this) on failure, so callers --
    including the CLI and the tkinter GUI -- have a single exception to catch and
    can show a clean message instead of a raw traceback.
    """
