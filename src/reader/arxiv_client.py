"""Fetch metadata and full text from arxiv papers via API + ar5iv HTML."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from lxml import html as lxml_html

DATA_DIR = Path(__file__).parent.parent.parent / "data"

ARXIV_API_URL = "https://export.arxiv.org/api/query"
AR5IV_HTML_URL = "https://ar5iv.labs.arxiv.org/html"


def fetch_arxiv_metadata(arxiv_id: str) -> dict:
    """Fetch paper metadata from the arxiv Atom API.

    Returns: {title, authors, abstract, published, categories, pdf_url}
    """
    resp = httpx.get(
        ARXIV_API_URL,
        params={"id_list": arxiv_id, "max_results": "1"},
        follow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(resp.text)
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"No arxiv entry found for ID: {arxiv_id}")

    title = entry.findtext("atom:title", "", ns).strip()
    title = re.sub(r"\s+", " ", title)

    authors = [
        a.findtext("atom:name", "", ns).strip()
        for a in entry.findall("atom:author", ns)
    ]

    abstract = entry.findtext("atom:summary", "", ns).strip()
    abstract = re.sub(r"\s+", " ", abstract)

    published = entry.findtext("atom:published", "", ns)[:10]  # YYYY-MM-DD

    categories = [
        c.get("term", "")
        for c in entry.findall("atom:category", ns)
        if c.get("term")
    ]

    pdf_url = ""
    for link in entry.findall("atom:link", ns):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "categories": categories,
        "pdf_url": pdf_url,
    }


def _html_to_markdown(tree) -> str:
    """Convert ar5iv HTML body to markdown-like plain text.

    Extracts headings, paragraphs, and figure/table captions.
    Math elements are rendered as their text content or alt text.
    """
    lines: list[str] = []

    # Find main article content — ar5iv wraps content in <article> or <div class="ltx_page_content">
    body = tree.find('.//article')
    if body is None:
        body = tree.find('.//*[@class="ltx_page_content"]')
    if body is None:
        body = tree.find('.//body')
    if body is None:
        return ""

    for elem in body.iter():
        tag = elem.tag
        text = (elem.text or "").strip()
        tail = (elem.tail or "").strip()

        if tag in ("h1", "h2"):
            full = _get_all_text(elem).strip()
            if full:
                lines.append(f"\n## {full}\n")
        elif tag in ("h3", "h4", "h5"):
            full = _get_all_text(elem).strip()
            if full:
                lines.append(f"\n### {full}\n")
        elif tag == "p":
            para_text = _get_all_text(elem).strip()
            if para_text:
                lines.append(para_text + "\n")
        elif tag == "figcaption":
            cap = _get_all_text(elem).strip()
            if cap:
                lines.append(f"[Figure: {cap}]\n")
        elif tag == "caption":
            cap = _get_all_text(elem).strip()
            if cap:
                lines.append(f"[Table: {cap}]\n")

    return "\n".join(lines)


def _get_all_text(elem) -> str:
    """Recursively extract all text from an element, handling math alt text."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag == "math":
            alt = child.get("alttext", "")
            if alt:
                parts.append(alt)
            else:
                parts.append(_get_all_text(child))
        elif child.tag in ("h1", "h2", "h3", "h4", "h5", "p", "figcaption", "caption"):
            # Skip nested block elements — they'll be processed in top-level iteration
            pass
        else:
            parts.append(_get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return " ".join(parts)


def fetch_arxiv_fulltext(arxiv_id: str, cache_filename: str) -> str:
    """Fetch full text from ar5iv HTML, convert to markdown, and cache.

    ar5iv provides an HTML5 rendering of arxiv papers.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / cache_filename

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    url = f"{AR5IV_HTML_URL}/{arxiv_id}"
    resp = httpx.get(url, follow_redirects=True, timeout=60)
    resp.raise_for_status()

    tree = lxml_html.fromstring(resp.content)
    markdown_text = _html_to_markdown(tree)

    if not markdown_text.strip():
        raise ValueError(f"No text extracted from ar5iv for {arxiv_id}. The paper may not be available in HTML format.")

    cache_path.write_text(markdown_text, encoding="utf-8")
    return markdown_text
