"""
Shared experience-requirement detection + title filters for the whole pipeline.
Import regex patterns from here — do NOT redefine them in other files.
"""
import re

# ── Title pre-filter regexes (single source of truth) ────────────────────────

INTERNSHIP_TITLE_RE = re.compile(
    r"\b(intern(ship)?|internships|trainee\s+program|apprentice(ship)?)\b",
    re.IGNORECASE,
)

SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?\s|lead\s|principal|staff\s+eng|engineering\s+manager|"
    r"director|head\s+of|vice\s+pres|vp\s+of|architect(?!\s+as))\b",
    re.IGNORECASE,
)

IRRELEVANT_TITLE_RE = re.compile(
    r"\b("
    r"android|flutter|ios\s+dev|swift\s+dev|kotlin|"
    r"devops|sre\s+|site\s+reliability|cloud\s+eng|"
    r"data\s+scientist|data\s+engineer|data\s+analyst|"
    r"machine\s+learning|ml\s+eng|pyspark|"
    r"business\s+analyst|bi\s+developer|"
    r"java\s+dev|java\s+eng|java\s+full|"
    r"\.net\s+dev|\.net\s+eng|dotnet|"
    r"php\s+dev|php\s+eng|"
    r"python\s+dev|python\s+eng|django\s+dev|"
    r"ruby\s+dev|golang\s+dev|go\s+dev|"
    r"c\+\+\s+dev|embedded\s+dev|"
    r"salesforce|sap\s+|"
    r"manufacturing|quality\s+assurance|qa\s+eng|"
    r"product\s+manager|product\s+owner|scrum\s+master|"
    r"technical\s+writer|technical\s+support|"
    r"guard\b|transportation\s+rep|relationship\s+manager"
    r")\b",
    re.IGNORECASE,
)

# Matches ONLY clear minimum/required experience of 2-20 years.
# Patterns deliberately narrow to avoid false positives:
#   - "up to X years" = ceiling, excluded
#   - "35 years of experience" (company history) = excluded (cap at 20)
#   - "candidates with 5+ years welcome" = requirement, included (the + marks floor)
EXP_MIN_RE = re.compile(
    # "2+ yrs", "3+ years"  — the + explicitly marks this as a minimum
    r"\b([2-9]|1\d|20)\s*\+\s*(?:years?|yrs?)"
    # "2-4 years experience", "2 to 4 yrs of experience", "2\-3 yrs" (LinkedIn markdown)
    r"|\b([2-9]|1\d|20)\s*\\?(?:[-–]|to)\s*\d+\s*(?:years?|yrs?)\s+(?:of\s+)?(?:\w+\s+){0,3}experience"
    # "minimum 2 years", "min 3 yrs", "at least 2 years"
    r"|\b(?:minimum|min\.?|at\s+least)\s+(?:of\s+)?([2-9]|1\d|20)\s+(?:years?|yrs?)"
    # "requires 2 years", "required: 3 years"
    r"|\brequires?\s+([2-9]|1\d|20)\s*\+?\s*(?:years?|yrs?)"
    # "must have 3 years", "should have 2+ years", "we need 2 years"
    r"|\b(?:must\s+have|should\s+have|we\s+need|need\s+to\s+have)\s+([2-9]|1\d|20)\s*\+?\s*(?:years?|yrs?)"
    # "experience: 3+", "experience required: 2"
    r"|\bexperience\s*(?:required)?\s*[:\-]\s*([2-9]|1\d|20)\s*\+?"
    # "3 years of relevant/professional/work/hands-on experience"
    r"|\b([2-9]|1\d|20)\s+(?:years?|yrs?)\s+(?:of\s+)?(?:relevant|professional|work|industry|hands.on)\s+experience"
    # "proven experience of 3 years", "experience of 2+ years"
    r"|\bexperience\s+of\s+([2-9]|1\d|20)\s*\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)

# Patterns that indicate a ceiling/welcome phrase — if found before a number, it's NOT a min req
_CEILING_MARKERS = ("up to", "upto", "maximum", "max ", "no more than", "less than",
                    "fewer than", "as many as", "welcome", "open to")


def has_experience_requirement(description: str) -> bool:
    """
    Return True if the job description has a MINIMUM experience requirement of 2+ years.
    Returns False for ceiling phrases like "up to 5 years welcome" or company history.
    """
    if not description or str(description).strip() in ("", "nan", "None"):
        return False

    for m in EXP_MIN_RE.finditer(description):
        # Check the 25 characters before the match for ceiling markers
        prefix = description[max(0, m.start() - 25): m.start()].lower()
        if any(marker in prefix for marker in _CEILING_MARKERS):
            continue  # this is a ceiling, not a floor — skip
        return True  # found a genuine minimum requirement

    return False


def find_experience_snippet(description: str) -> str | None:
    """Return a short snippet around the first minimum experience requirement, or None."""
    if not description or str(description).strip() in ("", "nan", "None"):
        return None

    for m in EXP_MIN_RE.finditer(description):
        prefix = description[max(0, m.start() - 25): m.start()].lower()
        if any(marker in prefix for marker in _CEILING_MARKERS):
            continue
        snippet = description[max(0, m.start() - 15): m.end() + 25].replace("\n", " ")
        return snippet.strip()

    return None
