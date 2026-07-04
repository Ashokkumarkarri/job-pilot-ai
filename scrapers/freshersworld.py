import asyncio, hashlib, random, yaml
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
    STEALTH = True
except ImportError:
    STEALTH = False


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


async def _scrape_keyword(keyword, max_jobs):
    kw_slug = keyword.lower().replace(" ", "-")
    url = f"https://www.freshersworld.com/jobs/search?keyword={keyword.replace(' ', '+')}&location=India&fresher=true"
    jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()
        if STEALTH:
            await stealth_async(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector(".job-container, .job-card, article.job, [class*='jobList']", timeout=10000)
            except Exception:
                pass
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200 + random.randint(200, 500))

            cards = await page.query_selector_all(".job-container, .job-card, article.job, li.job-listing")

            for card in cards[:max_jobs]:
                try:
                    title_el   = await card.query_selector("h2 a, h3 a, .job-title a, a.title")
                    company_el = await card.query_selector(".company-name, [class*='company']")
                    loc_el     = await card.query_selector(".location, [class*='location']")

                    title   = (await title_el.inner_text()).strip()   if title_el   else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    loc     = (await loc_el.inner_text()).strip()     if loc_el     else "India"
                    href    = await title_el.get_attribute("href")    if title_el   else ""

                    if not title or not href:
                        continue
                    job_url = href if href.startswith("http") else f"https://www.freshersworld.com{href}"
                    job_id  = hashlib.md5(job_url.encode()).hexdigest()
                    jobs.append({"job_id": job_id, "title": title, "company": company,
                                 "location": loc, "source": "freshersworld", "job_url": job_url,
                                 "description": "", "date_posted": "", "company_website": ""})
                except Exception:
                    continue
        except Exception as e:
            print(f"    Freshersworld error [{keyword}]: {e}")
        finally:
            await browser.close()
    return jobs


async def _scrape_all():
    config   = load_config()
    keywords = config["search"]["keywords"]
    max_jobs = config["scraping"].get("results_per_keyword", 25)
    delay    = config["scraping"].get("delay_between_requests", 3)
    results, seen = [], set()

    for kw in keywords:
        print(f"  [Freshersworld] {kw}")
        jobs = await _scrape_keyword(kw, max_jobs)
        new  = [j for j in jobs if j["job_id"] not in seen]
        for j in new:
            seen.add(j["job_id"])
            results.append(j)
        print(f"    +{len(new)} jobs")
        await asyncio.sleep(delay + random.random() * 2)
    return results


def scrape_freshersworld():
    jobs = asyncio.run(_scrape_all())
    print(f"  Freshersworld total: {len(jobs)}")
    return jobs
