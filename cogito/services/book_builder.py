"""Auto-generate book configuration YAML from a URL or file path."""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "books"


def slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text[:40]


def detect_source_type(source: str) -> tuple[str, dict]:
    """Detect source type and return (type, config_dict)."""
    if source.endswith('.pdf'):
        return "pdf", {"type": "pdf", "path": source}
    elif source.endswith('.epub'):
        return "epub", {"type": "epub", "path": source}
    elif "arxiv.org" in source:
        # Extract arxiv ID
        match = re.search(r'(\d{4}\.\d{4,5})', source)
        if match:
            arxiv_id = match.group(1)
            return "arxiv", {
                "type": "arxiv",
                "arxiv_id": arxiv_id,
                "cache_filename": f"arxiv_{arxiv_id}.md"
            }
    elif source.startswith("http"):
        parsed = urlparse(source)
        filename = Path(parsed.path).name or "downloaded.txt"
        return "url", {"type": "url", "url": source, "cache_filename": filename}
    elif Path(source).exists():
        suffix = Path(source).suffix.lower()
        if suffix == '.pdf':
            return "pdf", {"type": "pdf", "path": source}
        elif suffix == '.epub':
            return "epub", {"type": "epub", "path": source}
        else:
            return "local_file", {"type": "local_file", "path": source}
    return "url", {"type": "url", "url": source, "cache_filename": "book.txt"}


def build_config(title: str, author: str, source: str, language: str = "ja") -> dict:
    """Build a book config dict."""
    source_type, source_config = detect_source_type(source)
    config_key = slugify(f"{author}_{title}")

    return {
        "config_key": config_key,
        "config": {
            "title": title,
            "author": author,
            "language": language,
            "source": source_config,
            "chunking": {
                "method": "token",
                "max_tokens": 4000,
                "overlap": 200,
            },
            "key_terms": [],
            "research_queries": [
                f"{title} {author} summary",
                f"{title} key concepts analysis",
                f"{author} philosophical background",
            ],
        }
    }


def add_book(title: str, author: str, source: str, language: str = "ja") -> Path:
    """Generate and save a book config YAML. Returns the config file path."""
    try:
        import yaml
    except ImportError:
        sys.path.insert(0, "/workspace/group/.pypackages")
        import yaml

    result = build_config(title, author, source, language)
    config_key = result["config_key"]
    config = result["config"]

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CONFIG_DIR / f"{config_key}.yaml"

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return output_path
