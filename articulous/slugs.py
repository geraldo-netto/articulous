"""Canonical ASCII route-slug normalization."""
import re


def normalize_slug(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")

