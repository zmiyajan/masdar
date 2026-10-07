"""File helpers shared by adapters."""

from pathlib import Path


def write_atomically(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` so readers never see a half-written file.

    The bytes go to a sibling ``.partial`` file that is then renamed over the
    target; a rename within one directory is atomic on POSIX file systems.
    """
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(content)
    partial.replace(path)
