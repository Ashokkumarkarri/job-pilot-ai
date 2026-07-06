"""
Email drafter — template-based only, zero LLM calls.
draft_email_lite() is the only function used by the pipeline.
"""

PORTFOLIO = "https://kumarnaidukarri.github.io/KumarPortfolio/"
GITHUB    = "https://github.com/kumarnaidukarri"
LINKEDIN  = "https://www.linkedin.com/in/kumarnaidukarri/"

TECH_KEYWORDS = [
    "React.js", "ReactJS", "React", "Node.js", "NodeJS", "Node",
    "Express.js", "Express", "MongoDB", "Mongo", "Redux", "Socket.io",
    "Tailwind", "JWT", "REST API", "REST", "CRUD", "Firebase", "Axios",
    "JavaScript", "TypeScript", "Next.js", "MERN",
]

GENERIC_BODY = """\
Hi,

I hope you're doing well.

I'm a Full Stack Developer with experience building web apps using React.js, Node.js, Express.js, and MongoDB.{tech_line} I completed a 9-month internship at Revidd where I built React.js features using Redux and Axios. After that, I worked as a Junior Software Developer at BiziQuick, developing an ERP & CRM platform with React components and REST APIs.

I'd love to explore if there's a fit for the {title} role at {company}.

Portfolio: {portfolio}
GitHub: {github}
LinkedIn: {linkedin}

Please find my resume attached. Thank you for your time.

Regards,
Kumar Naidu
kumarnaidukarri22@gmail.com | +91-8500279547"""


def _extract_tech_mentions(description: str, max_n: int = 2) -> list:
    if not description or str(description).strip() in ("", "nan", "None"):
        return []
    desc_lower = str(description).lower()
    found, found_lower = [], []
    for kw in TECH_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower not in desc_lower:
            continue
        if any(kw_lower in f or f in kw_lower for f in found_lower):
            continue
        found.append(kw)
        found_lower.append(kw_lower)
        if len(found) >= max_n:
            break
    return found


def draft_email_lite(job) -> str:
    """Template-based cold email — no LLM, no API calls."""
    title   = str(job.get("title", "")).split("|")[0].strip()
    company = str(job.get("company", "")).strip()
    desc    = job.get("description", "")

    tech_found = _extract_tech_mentions(desc)
    if tech_found:
        tech_str  = " and ".join(tech_found) if len(tech_found) <= 2 else ", ".join(tech_found)
        tech_line = f" I noticed the role works with {tech_str} — that lines up well with my experience."
    else:
        tech_line = ""

    subject = f"Application – {title} at {company} | Kumar Naidu"
    body    = GENERIC_BODY.format(
        tech_line=tech_line, title=title, company=company,
        portfolio=PORTFOLIO, github=GITHUB, linkedin=LINKEDIN,
    )
    return f"SUBJECT: {subject}\n\n{body}"
