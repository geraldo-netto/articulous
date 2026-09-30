"""Native publication selection and validated platform capabilities."""
import sys

from ..publication import PublicationCapabilities


def publication_capabilities() -> PublicationCapabilities:
    available = sys.platform == 'linux'
    return PublicationCapabilities(sys.platform, available, available, available, available)


def get_publication_backend():
    if not publication_capabilities().available:
        raise RuntimeError(f'Native publication is unsupported on {sys.platform}')
    from .posix import PosixPublicationBackend
    return PosixPublicationBackend()
