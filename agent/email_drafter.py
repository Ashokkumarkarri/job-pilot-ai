import json
import os

import requests
import yaml
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_groq_client = None

PORTFOLIO = "https://kumarnaidukarri.github.io/KumarPortfolio/"
GITHUB    = "https://github.com/kumarnaidukarri"
LINKEDIN  = "https://www.linkedin.com/in/kumarnaidukarri/"


def _get_groq():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


def _get_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _build_prompt(job, resume_text, hr_name=None):
    title   = job.get("title", "")
    company = job.get("company", "")
    desc    = str(job.get("description", ""))[:400]

    return f"""Write a short, human-sounding cold email for a job application.
Return JSON only with keys "subject" and "body".

CANDIDATE: Kumar Naidu Karri
- Full Stack Developer (MERN Stack)
- Internship (9 months) at Revidd: built and maintained React.js features, worked with Redux, Axios, Firebase
- Junior Software Developer (3 months) at BiziQuick: ERP & CRM platform, React components, REST APIs, full CRUD operations
- Skills: React.js, Node.js, Express.js, MongoDB, Redux, Socket.io, Tailwind CSS, JWT, Git

JOB: {title} at {company}
DESCRIPTION: {desc}

Write the email in THIS exact style — short, real, no corporate fluff:

---
Subject: {title} at {company} – Kumar Naidu

Hi,

I hope you're doing well.

[1 sentence: brief intro — "I'm a Full Stack Developer with experience building web apps using React.js, Node.js, and MongoDB" — tweak stack to match the job]

[2-3 sentences: mention Revidd internship and BiziQuick role specifically — what was built, honest, relevant to THIS job description]

I'd love to explore if there's a fit for the {title} role at {company}.

Portfolio: {PORTFOLIO}
GitHub: {GITHUB}
LinkedIn: {LINKEDIN}

Please find my resume attached. Thank you for your time.

Regards,
Kumar Naidu
kumarnaidukarri22@gmail.com | +91-8500279547
---

STRICT RULES:
- Under 150 words total (body only)
- Sound like a real person wrote it, not an AI
- Do NOT say: "passionate", "seasoned", "leverage", "throughout my career", "excited to apply", "I am writing to express"
- Do NOT mention "fresher" or "junior" — just describe what was built
- Keep portfolio/github/linkedin links exactly as shown
- End with exact signature shown above

Return: {{"subject": "...", "body": "..."}}"""


def _draft_via_groq(job, resume_text, hr_name, model):
    response = _get_groq().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _build_prompt(job, resume_text, hr_name)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _draft_via_ollama(job, resume_text, hr_name, model):
    import re
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": "/no_think\n" + _build_prompt(job, resume_text, hr_name),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.3, "think": False},
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["response"]
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return json.loads(raw)


TECH_KEYWORDS = [
    "React.js", "ReactJS", "React", "Node.js", "NodeJS", "Node",
    "Express.js", "Express", "MongoDB", "Mongo", "Redux", "Socket.io",
    "Tailwind", "JWT", "REST API", "REST", "CRUD", "Firebase", "Axios",
    "JavaScript", "TypeScript", "Next.js", "MERN",
]

GENERIC_BODY_LITE = """\
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
    """Find up to max_n tech keywords from the job description that match the candidate's stack."""
    if not description or str(description).strip() in ("", "nan", "None"):
        return []
    desc_lower = str(description).lower()
    found = []
    found_lower = []
    for kw in TECH_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower not in desc_lower:
            continue
        # skip if this keyword overlaps with one already found (e.g. "React" vs "React.js")
        if any(kw_lower in f or f in kw_lower for f in found_lower):
            continue
        found.append(kw)
        found_lower.append(kw_lower)
        if len(found) >= max_n:
            break
    return found


def draft_email_lite(job) -> str:
    """
    Build a cold email with NO LLM call — fixed template + 2 personalized lines:
    1. A line referencing specific tech mentioned in the job description (if found)
    2. The role + company name (always)
    Fast, reliable, no rate limits.
    """
    title   = str(job.get("title", "")).split("|")[0].strip()
    company = str(job.get("company", "")).strip()
    desc    = job.get("description", "")

    tech_found = _extract_tech_mentions(desc)
    if tech_found:
        tech_str = " and ".join(tech_found) if len(tech_found) <= 2 else ", ".join(tech_found)
        tech_line = f" I noticed the role works with {tech_str} — that lines up well with my experience."
    else:
        tech_line = ""

    subject = f"Application – {title} at {company} | Kumar Naidu"
    body = GENERIC_BODY_LITE.format(
        tech_line=tech_line,
        title=title,
        company=company,
        portfolio=PORTFOLIO,
        github=GITHUB,
        linkedin=LINKEDIN,
    )
    return f"SUBJECT: {subject}\n\n{body}"


def draft_email(job, resume_text, hr_name=None):
    config       = _get_config()
    use_ollama   = config["matching"].get("use_ollama", False)
    groq_model   = config["matching"].get("groq_model", "llama-3.1-8b-instant")
    ollama_model = config["matching"].get("ollama_model", "qwen3:8b")

    if use_ollama:
        result = _draft_via_ollama(job, resume_text, hr_name, ollama_model)
    else:
        try:
            result = _draft_via_groq(job, resume_text, hr_name, groq_model)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                print("    Groq rate limit — using local Hermes for email draft...")
                result = _draft_via_ollama(job, resume_text, hr_name, ollama_model)
            else:
                raise

    subject = result.get("subject", "")
    body    = result.get("body", "")
    return f"SUBJECT: {subject}\n\n{body}"
