"""Exception hierarchy for Masdar.

Every error raised on purpose by Masdar derives from `MasdarError`, so callers can
catch Masdar failures without also swallowing unrelated bugs.
"""


class MasdarError(Exception):
    """Base class for all errors raised deliberately by Masdar."""


class InvalidDomainObjectError(MasdarError, ValueError):
    """A domain object was constructed with values that break its invariants."""


class ArticleHeadingError(MasdarError, ValueError):
    """An article heading could not be parsed into an article number."""


class SourceFormatError(MasdarError):
    """A source document does not have the structure Masdar expects."""


class SourceFetchError(MasdarError):
    """A source document could not be fetched."""


class UnknownLawError(MasdarError, KeyError):
    """A law id is not in the catalog."""


class DataIntegrityError(MasdarError):
    """Built data violates an invariant (e.g. two current articles share a number)."""
