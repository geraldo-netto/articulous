"""ARCH-008: normalized membership and immutable cached language projections."""
from dataclasses import dataclass

import pytest

from articulous.article_contracts import PublicationPolicy
from articulous.catalogue import PublicationCatalogue, TagCount


@dataclass(frozen=True)
class Metadata:
    lang: str
    tags: tuple[str, ...]
    policy: PublicationPolicy


def article(language='en', listed=True):
    return Metadata(language, ('C++', 'C#', 'C++', '!!!'),
                    PublicationPolicy(True, listed, listed, listed, listed))


def test_arch008_normalized_membership_and_cached_views():
    first = article()
    catalogue = PublicationCatalogue([first, first, article(listed=False)], ['en', 'es'])
    assert catalogue.tag_counts('en') == (TagCount('c', 2, 'C++'),)
    assert catalogue.tag_counts('en') is catalogue.tag_counts('en')
    assert catalogue.tag_counts('es') == ()
    assert catalogue.articles[0] is first
    with pytest.raises(ValueError, match='disabled'):
        catalogue.tag_counts('fr')


@pytest.mark.parametrize('languages', ['en', b'en', [], ['en', 'en'], [''], [42], ['en', ' ']])
def test_arch008_invalid_language_collections(languages):
    with pytest.raises(ValueError):
        PublicationCatalogue([], languages)


@pytest.mark.parametrize('articles', ['bad', b'bad', {}, [None], [article('disabled')]])
def test_arch008_invalid_article_collections(articles):
    with pytest.raises(ValueError):
        PublicationCatalogue(articles, ['en'])
