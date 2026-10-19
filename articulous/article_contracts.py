"""Publication policy/state independent of article parsing and native storage."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PublicationPolicy:
    page: bool
    listing: bool
    rss: bool
    sitemap: bool
    search: bool


_PUBLICATION_POLICIES = {
    "published": PublicationPolicy(True, True, True, True, True),
    "unlisted": PublicationPolicy(True, False, False, False, False),
    "draft": PublicationPolicy(False, False, False, False, False),
    "private": PublicationPolicy(False, False, False, False, False),
    "scheduled": PublicationPolicy(False, False, False, False, False),
}
@dataclass(frozen=True)
class PublicationState:
    name: str = "published"
    publish_at: Optional[datetime] = None
    evaluated_at: Optional[datetime] = None

    @property
    def policy(self) -> PublicationPolicy:
        if self.name == "scheduled" and self._published_now():
            return _PUBLICATION_POLICIES["published"]
        return _PUBLICATION_POLICIES[self.name]

    def _published_now(self) -> bool:
        if self.publish_at is None:
            return False
        now = self.evaluated_at or datetime.now(tz=self.publish_at.tzinfo)
        return self.publish_at <= now

