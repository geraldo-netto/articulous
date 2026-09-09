"""Optional article JSON-LD with safe HTML script serialization."""
import json


def article_jsonld(article) -> str:
    if not article.structured_data or not article.url.startswith(("https://", "http://")):
        return ""
    data = {
        "@context": "https://schema.org",
        "@type": article.structured_data,
        "mainEntityOfPage": article.url,
        "headline": article.title,
        "description": article.description,
        "datePublished": article.datetime.isoformat(),
        "dateModified": article.modified,
        "image": article.image,
    }
    data = {key: value for key, value in data.items() if value}
    if article.author:
        data["author"] = {"@type": "Person", "name": article.author}
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return encoded.translate({ord(char): f"\\u{ord(char):04x}" for char in "<>&\u2028\u2029"})
