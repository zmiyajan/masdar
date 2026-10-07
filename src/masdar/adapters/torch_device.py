"""Pick the torch device that local models run on."""


def select_device() -> str:
    """The fastest available torch device: Apple ``mps``, then ``cuda``, then ``cpu``."""
    # Imported here, not at module level: torch is an optional extra (`ml`).
    import torch  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
