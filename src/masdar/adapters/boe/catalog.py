"""The laws Masdar indexes, and where the portal publishes them."""

from dataclasses import dataclass

from masdar.domain.errors import UnknownLawError

_BASE_URL = "https://laws.boe.gov.sa/BoeLaws/Laws/LawDetails"


@dataclass(frozen=True, slots=True)
class BoeLaw:
    """A law published on laws.boe.gov.sa.

    Attributes:
        law_id: Masdar's stable slug for the law.
        guid: The portal's identifier, taken from the law's URL.
    """

    law_id: str
    guid: str

    @property
    def url(self) -> str:
        """The page that holds the full text of the law."""
        return f"{_BASE_URL}/{self.guid}/1"


CATALOG: tuple[BoeLaw, ...] = (
    BoeLaw("labor-law", "08381293-6388-48e2-8ad2-a9a700f2aa94"),
    BoeLaw("pdpl", "b7cfae89-828e-4994-b167-adaa00e37188"),
    BoeLaw("companies-law", "a8376aea-1bc3-49d4-9027-aed900b555af"),
)


def find_law(law_id: str) -> BoeLaw:
    """Look up a law by its slug.

    Raises:
        UnknownLawError: If ``law_id`` is not in `CATALOG`.
    """
    for law in CATALOG:
        if law.law_id == law_id:
            return law
    known = ", ".join(law.law_id for law in CATALOG)
    raise UnknownLawError(f"Unknown law {law_id!r}; known laws: {known}")
