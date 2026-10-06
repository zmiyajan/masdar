"""Exception hierarchy for Masdar.

Every error raised on purpose by Masdar derives from `MasdarError`, so callers can
catch Masdar failures without also swallowing unrelated bugs.
"""


class MasdarError(Exception):
    """Base class for all errors raised deliberately by Masdar."""


class InvalidDomainObjectError(MasdarError, ValueError):
    """A domain object was constructed with values that break its invariants."""
