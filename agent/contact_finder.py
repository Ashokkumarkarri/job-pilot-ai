import asyncio
import re
import requests
from urllib.parse import unquote, urlparse, quote_plus

from playwright.async_api import async_playwright

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?)?[6-9]\d{9}"
    r"|0\d{2,4}[\s\-]?\d{6,8}"
)

SKIP_DOMAINS  = {"example.com", "sentry.io", "wixpress.com", "googleapis.com",
                 "w3.org", "schema.org", "placeholder.com", "ingest.sentry.io",
                 "vs-errors.eightfold.ai"}

INVALID_TLDS = {"pu", "onion", "local", "internal", "localhost", "invalid", "test"}
_HTML_ENTITY_RE = re.compile(r"u00[0-9a-f]{2}", re.IGNORECASE)
SKIP_PREFIXES = {"noreply", "no-reply", "support", "info", "admin",
                 "test", "example", "webmaster", "postmaster", "sales",
                 "billing", "upgrade", "renewal", "cancellation", "invoice",
                 "newsletter", "unsubscribe", "bounce", "mailer", "daemon",
                 "press", "media", "pr", "fraud", "abuse", "legal",
                 "privacy", "security", "help", "feedback", "contact",
                 "hello", "hi", "hey", "team", "general", "office",
                 "customer", "service", "premium", "referral", "partner",
                 "affiliate", "pay", "payment", "slice",
                 "suspicious", "report"}
HR_KEYWORDS   = {"hr", "recruit", "talent", "career", "hiring",
                 "people", "jobs", "apply", "humanresource"}

JOB_SITES = {
    "linkedin", "indeed", "naukri", "glassdoor", "monster", "foundit",
    "shine", "internshala", "timesjobs", "hirist", "wellfound", "cutshort",
    "freshersworld", "remoteok", "remotive", "ycombinator", "news.ycombinator",
    "workingnomads", "jobicy", "arbeitnow", "ziprecruiter", "simplyhired",
    "careerjet", "apna", "iimjobs",
}

CONTACT_PATHS = [
    "/contact", "/contact-us", "/about", "/about-us",
    "/careers", "/jobs", "/team", "/our-team", "/hire",
]

FORM_SELECTORS = [
    "form[action*='contact']",
    "form[action*='apply']",
    "a[href*='contact']",
    "a[href*='apply']",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}


def _rank(emails):
    hr   = [e for e in emails if any(k in e.lower() for k in HR_KEYWORDS)]
    rest = [e for e in emails if e not in hr]
    return hr + rest


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico",
              ".bmp", ".avif", ".tiff", ".tif", ".woff", ".woff2", ".css",
              ".js", ".json", ".xml", ".pdf", ".zip"}

PLACEHOLDER_EMAILS = {
    "yourname@email.com", "user@domain.com", "joe.smith@company.com",
    "name@company.com", "example@example.com", "test@test.com",
    "tony.stark@stark.com", "email@email.com",
}


def _clean(raw_emails):
    out, seen = [], set()
    for e in raw_emails:
        e = e.lower().strip()
        if e in seen:
            continue
        if e in PLACEHOLDER_EMAILS:
            continue
        parts = e.split("@")
        if len(parts) != 2:
            continue
        prefix, domain = parts
        # Block HTML-entity encoded prefixes (e.g. u003ehelp, u0022name)
        if _HTML_ENTITY_RE.search(prefix):
            continue
        # Skip image/asset filenames mistaken for emails (e.g. logo@2x.png)
        if any(domain.endswith(ext) for ext in IMAGE_EXTS):
            continue
        # Skip encoded/obfuscated domains (too short TLD or no dot)
        tld_parts = domain.split(".")
        if len(tld_parts) < 2 or len(tld_parts[-1]) < 2:
            continue
        # Block known-invalid / non-IANA TLDs (e.g. .pu from ROT13 encoded addresses)
        if tld_parts[-1].lower() in INVALID_TLDS:
            continue
        if domain in SKIP_DOMAINS or any(domain.endswith("." + d) for d in SKIP_DOMAINS):
            continue
        if any(prefix.startswith(p) for p in SKIP_PREFIXES):
            continue
        seen.add(e)
        out.append(e)
    return out


def _clean_phone(numbers):
    out, seen = [], set()
    for n in numbers:
        n = re.sub(r"[\s\-]", "", n)
        if n in seen or len(n) < 10:
            continue
        seen.add(n)
        out.append(n)
    return out


def _discover_website(company_name: str) -> str | None:
    """Find a company's official domain using Clearbit autocomplete, with DDG as fallback."""
    # 1. Clearbit autocomplete (free, no auth)
    try:
        url  = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={quote_plus(company_name)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        hits = resp.json()
        for hit in hits[:3]:
            domain = hit.get("domain", "")
            if domain and not any(js in domain for js in JOB_SITES):
                return f"https://{domain}"
    except Exception:
        pass

    # 2. DuckDuckGo Instant Answer API
    try:
        url  = f"https://api.duckduckgo.com/?q={quote_plus(company_name)}&format=json&no_html=1&skip_disambig=1"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        data = resp.json()
        site = data.get("OfficialSite") or data.get("AbstractURL", "")
        if site and "wikipedia" not in site:
            parsed = urlparse(site)
            domain = parsed.netloc.replace("www.", "").lower()
            if domain and not any(js in domain for js in JOB_SITES):
                return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass

    return None


async def _fetch(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=12000)
        return await page.content()
    except Exception:
        return ""


async def _find_contact_form(page):
    for sel in FORM_SELECTORS:
        el = await page.query_selector(sel)
        if el:
            href   = await el.get_attribute("href")   or ""
            action = await el.get_attribute("action") or ""
            return href or action
    return None


async def _find_async(base_url: str):
    if not base_url or str(base_url).strip() in ("", "nan", "None", "none"):
        return {}

    base_url = str(base_url).rstrip("/")
    urls_to_check = [base_url] + [base_url + p for p in CONTACT_PATHS]

    all_emails, all_phones, contact_form = [], [], None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page    = await context.new_page()

        for url in urls_to_check:
            html = await _fetch(page, url)
            if not html:
                continue

            all_emails.extend(EMAIL_RE.findall(html))
            all_phones.extend(PHONE_RE.findall(html))

            if not contact_form:
                contact_form = await _find_contact_form(page)

            # Stop early if we have at least 2 HR emails
            cleaned  = _clean(all_emails)
            hr_found = [e for e in cleaned if any(k in e for k in HR_KEYWORDS)]
            if len(hr_found) >= 2:
                break

        await browser.close()

    ranked   = _rank(_clean(all_emails))
    phones_c = _clean_phone(all_phones)

    return {
        "email_1":      ranked[0] if len(ranked) > 0 else None,
        "email_2":      ranked[1] if len(ranked) > 1 else None,
        "email_3":      ranked[2] if len(ranked) > 2 else None,
        "name":         None,
        "phone":        phones_c[0] if phones_c else None,
        "contact_form": contact_form,
    }


def find_contact(company_website: str = "", company_name: str = "") -> dict:
    """
    Find HR contact info for a company.
    If company_website is blank, discovers it via DuckDuckGo first.
    """
    website = str(company_website).strip() if company_website else ""
    if website.lower() in ("", "nan", "none"):
        website = ""

    if not website and company_name:
        print(f"    No website for '{company_name}' — searching DuckDuckGo...")
        website = _discover_website(company_name)
        if website:
            print(f"    Found: {website}")
        else:
            print(f"    Could not resolve website for '{company_name}'")
            return {}

    if not website:
        return {}

    try:
        return asyncio.run(_find_async(website))
    except Exception as e:
        print(f"    Contact finder error: {e}")
        return {}
