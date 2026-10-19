"""Native publication capability data, independent of lifecycle implementations."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationCapabilities:
    platform: str
    available: bool
    staging: bool
    rollback: bool
    journal_recovery: bool
    atomic_visibility: bool = False
    power_loss_durability: bool = False

