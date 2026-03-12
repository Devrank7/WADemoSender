"""Website scraper — extracts structured business data from URLs.

Returns a concise text summary instead of raw HTML, saving 90%+ tokens
when sub-agents need to research a lead's website.

Usage as CLI:
    python3 -m _shared.scraper <URL> [--json]

Usage as module:
    from _shared.scraper import scrape_website
    result = scrape_website("https://example.com")
    print(result["summary"])  # concise text summary
"""

import json
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────
# Config
# ──────────────────────────────────────────

TIMEOUT = 15
MAX_PAGE_SIZE = 500_000  # 500KB max per page
MAX_PAGES = 5  # max subpages to crawl
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Subpage paths to look for (ordered by priority)
SUBPAGE_PATHS = [
    "/services", "/servicos", "/servicios", "/pricing", "/precos", "/precios",
    "/about", "/sobre", "/acerca", "/contact", "/contato", "/contacto",
    "/programs", "/programas", "/courses", "/cursos",
    "/testimonials", "/depoimentos", "/testimonios",
    "/coaching", "/mentoria", "/consultoria",
]

# Noise selectors to remove before extracting text
NOISE_SELECTORS = [
    "script", "style", "noscript", "iframe", "svg", "path",
    "nav", "footer", "header",
    ".cookie-banner", ".cookie-consent", ".popup", ".modal",
    "#cookie", "#gdpr", "#consent",
    "[class*='cookie']", "[class*='gdpr']", "[class*='consent']",
    "[class*='popup']", "[class*='modal']", "[class*='banner']",
    "[class*='sidebar']", "[class*='widget']", "[class*='social']",
    "[class*='share']", "[class*='newsletter']", "[class*='subscribe']",
]


# ──────────────────────────────────────────
# Core scraper
# ──────────────────────────────────────────

def _fetch(url: str) -> str | None:
    """Fetch a URL, return HTML text or None on failure."""
    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return None
        return resp.text[:MAX_PAGE_SIZE]
    except Exception:
        return None


def _clean_text(soup: BeautifulSoup) -> str:
    """Remove noise elements and extract clean text."""
    for selector in NOISE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove very short lines (likely UI fragments)
    lines = [l for l in text.split("\n") if len(l.strip()) > 2]
    return "\n".join(lines)


def _extract_meta(soup: BeautifulSoup) -> dict:
    """Extract meta tags (title, description, OG data)."""
    meta = {}
    title_tag = soup.find("title")
    if title_tag:
        meta["title"] = title_tag.get_text(strip=True)

    for tag in soup.find_all("meta"):
        name = tag.get("name", tag.get("property", "")).lower()
        content = tag.get("content", "").strip()
        if not content:
            continue
        if name in ("description", "og:description"):
            meta["description"] = content[:300]
        elif name in ("og:title",):
            meta.setdefault("title", content)
        elif name == "og:image":
            meta["image"] = content
        elif name in ("author", "og:site_name"):
            meta.setdefault("business_name", content)

    return meta


def _extract_emails(text: str) -> list[str]:
    """Find email addresses in text."""
    return list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)))[:3]


def _extract_phones(text: str) -> list[str]:
    """Find phone numbers in text."""
    patterns = re.findall(r"[\+]?[\d\s\-\(\)]{10,20}", text)
    phones = []
    for p in patterns:
        digits = re.sub(r"[^\d+]", "", p)
        if len(digits) >= 10:
            phones.append(p.strip())
    return list(set(phones))[:3]


def _extract_prices(text: str) -> list[str]:
    """Find price mentions in text."""
    patterns = [
        r"R\$\s*[\d.,]+",           # Brazilian Real
        r"€\s*[\d.,]+",             # Euro
        r"\$\s*[\d.,]+",            # Dollar/Peso
        r"[\d.,]+\s*(?:reais|euros|dollars|pesos)",
        r"(?:a partir de|from|desde)\s*R?\$?\s*[\d.,]+",
    ]
    prices = []
    for pat in patterns:
        prices.extend(re.findall(pat, text, re.IGNORECASE))
    return list(set(prices))[:10]


def _extract_services(text: str) -> list[str]:
    """Extract service/program names from headings and lists."""
    services = []
    # Look for common service-related patterns
    service_patterns = [
        r"(?:coaching|mentoria|consultoria|programa|curso|treinamento|workshop|sessao|session|program|course|training)\s+(?:de\s+)?[\w\s]{3,40}",
    ]
    for pat in service_patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        services.extend(m.strip() for m in matches)
    return list(set(services))[:15]


def _find_subpages(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Find relevant subpage URLs from the homepage."""
    found = []
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Same domain only
        if parsed.netloc != base_domain:
            continue

        path = parsed.path.rstrip("/").lower()

        # Check against known subpage paths
        for sp in SUBPAGE_PATHS:
            if sp in path and full_url not in found:
                found.append(full_url)
                break

    return found[:MAX_PAGES]


def _extract_headings(soup: BeautifulSoup) -> list[str]:
    """Extract h1-h3 headings."""
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 3 and len(text) < 200:
            headings.append(text)
    return headings[:20]


# ──────────────────────────────────────────
# Main scraper function
# ──────────────────────────────────────────

def scrape_website(url: str) -> dict:
    """Scrape a website and return structured business data.

    Returns dict with keys:
        url, business_name, description, services, prices,
        contact (emails, phones), headings, page_texts, summary
    """
    result = {
        "url": url,
        "business_name": "",
        "description": "",
        "services": [],
        "prices": [],
        "emails": [],
        "phones": [],
        "headings": [],
        "pages_scraped": 0,
        "summary": "",
        "error": None,
    }

    # Normalize URL
    if not url.startswith("http"):
        url = "https://" + url

    # Fetch homepage
    html = _fetch(url)
    if not html:
        result["error"] = f"Failed to fetch {url}"
        result["summary"] = f"ERROR: Could not access {url}"
        return result

    soup = BeautifulSoup(html, "html.parser")
    meta = _extract_meta(soup)
    clean = _clean_text(soup)
    headings = _extract_headings(soup)

    result["business_name"] = meta.get("business_name", meta.get("title", ""))
    result["description"] = meta.get("description", "")
    result["headings"] = headings
    result["emails"] = _extract_emails(clean)
    result["phones"] = _extract_phones(clean)
    result["prices"] = _extract_prices(clean)
    result["services"] = _extract_services(clean)
    result["pages_scraped"] = 1

    # Collect all text
    all_text = [f"=== HOME ({url}) ===", clean[:3000]]

    # Find and scrape subpages
    subpages = _find_subpages(soup, url)
    for sub_url in subpages:
        sub_html = _fetch(sub_url)
        if not sub_html:
            continue

        sub_soup = BeautifulSoup(sub_html, "html.parser")
        sub_clean = _clean_text(sub_soup)
        sub_headings = _extract_headings(sub_soup)

        result["headings"].extend(sub_headings)
        result["emails"].extend(_extract_emails(sub_clean))
        result["phones"].extend(_extract_phones(sub_clean))
        result["prices"].extend(_extract_prices(sub_clean))
        result["services"].extend(_extract_services(sub_clean))
        result["pages_scraped"] += 1

        # Identify page type from URL
        path = urlparse(sub_url).path
        label = path.strip("/").split("/")[-1] if path.strip("/") else "page"
        all_text.append(f"\n=== {label.upper()} ({sub_url}) ===")
        all_text.append(sub_clean[:2000])

    # Deduplicate
    result["emails"] = list(set(result["emails"]))[:3]
    result["phones"] = list(set(result["phones"]))[:3]
    result["prices"] = list(set(result["prices"]))[:10]
    result["services"] = list(set(result["services"]))[:15]
    result["headings"] = list(dict.fromkeys(result["headings"]))[:20]

    # Build concise summary
    summary_parts = []
    summary_parts.append(f"WEBSITE: {url}")

    if result["business_name"]:
        summary_parts.append(f"BUSINESS: {result['business_name']}")
    if result["description"]:
        summary_parts.append(f"DESCRIPTION: {result['description']}")

    if result["services"]:
        summary_parts.append(f"SERVICES: {', '.join(result['services'][:10])}")
    if result["prices"]:
        summary_parts.append(f"PRICES: {', '.join(result['prices'][:8])}")
    if result["emails"]:
        summary_parts.append(f"EMAILS: {', '.join(result['emails'])}")
    if result["phones"]:
        summary_parts.append(f"PHONES: {', '.join(result['phones'])}")

    if result["headings"]:
        summary_parts.append(f"KEY SECTIONS: {', '.join(result['headings'][:10])}")

    # Add condensed page text (max ~2000 chars total for the summary)
    full_text = "\n".join(all_text)
    # Truncate to keep summary concise
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "\n[...truncated]"
    summary_parts.append(f"\nPAGE CONTENT:\n{full_text}")

    result["summary"] = "\n".join(summary_parts)
    return result


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m _shared.scraper <URL> [--json]")
        sys.exit(1)

    url = sys.argv[1]
    as_json = "--json" in sys.argv

    result = scrape_website(url)

    if as_json:
        # Print structured JSON (without the full summary text)
        output = {k: v for k, v in result.items() if k != "summary"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(result["summary"])


if __name__ == "__main__":
    main()
