"""Search profiles — what to look for and which sheet tab the results go to.

Each source module's fetch(profile) uses the profile's patterns/queries instead of
hardcoded QA keywords. Add a new profile here to search for a new kind of role.
"""

import re
from dataclasses import dataclass, field


def compile_patterns(words: list[str]) -> list[re.Pattern]:
    # Word boundaries avoid substring false positives (e.g. "Infoniqa" contains "qa")
    return [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words]


@dataclass
class Profile:
    name: str
    sheet: str                      # tab in the Google Spreadsheet
    keywords: list[str]             # matched against the job title
    adzuna_queries: list[str]
    jsearch_queries: list[str]
    remoteok_tags: list[str]
    remotive_categories: list[str]
    exclude: set[str] = field(default_factory=lambda: {"intern", "staz", "praktykant", "junior"})
    use_pracuj: bool = False        # pracujwit.pl RSS is a testing-only category feed
    regional_where: list[str] = field(default_factory=list)    # cities searched on Adzuna PL (on-site / hybrid roles near home)
    regional_queries: list[str] = field(default_factory=list)  # what to search for in those cities
    regional_cities: list[str] = field(default_factory=list)   # lower-case city names accepted from NoFluffJobs even if not fully remote

    def __post_init__(self):
        self.patterns = compile_patterns(self.keywords)

    def matches(self, title: str) -> bool:
        return any(p.search(title) for p in self.patterns)

    def excluded(self, title: str) -> bool:
        low = title.lower()
        return any(kw in low for kw in self.exclude)


QA = Profile(
    name="QA",
    sheet="Testing",
    keywords=[
        "qa", "quality assurance", "test automation", "playwright", "sdet",
        "tester", "qa engineer", "test engineer", "automated testing",
        "selenium", "cypress", "automation engineer", "quality engineer",
    ],
    adzuna_queries=[
        "QA automation remote",
        "test automation engineer remote",
        "SDET remote",
        "Playwright QA remote",
    ],
    jsearch_queries=[
        "QA automation engineer remote",
        "SDET Playwright TypeScript remote",
        "quality assurance test automation UNDP UNICEF ILO WHO remote",
    ],
    remoteok_tags=["qa-engineer", "testing", "sdet"],
    remotive_categories=["qa", "testing", "software-dev"],
    use_pracuj=True,
)

# Implementation / consulting / AI-automation roles that fit: no-code platform logic,
# client contact, training, troubleshooting, working with AI agents (MCP).
CONSULTING = Profile(
    name="Consulting",
    sheet="Consulting",
    keywords=[
        "implementation consultant", "implementation specialist", "implementation engineer",
        "solutions engineer", "solutions consultant", "solution consultant", "solutions architect",
        "technical consultant", "functional consultant", "business analyst", "systems analyst",
        "customer success engineer", "technical account manager", "technical trainer",
        "forward deployed engineer", "integration specialist", "integration engineer",
        "low-code", "low code", "no-code", "no code",
        "power platform", "power apps", "power automate", "mendix", "outsystems", "ferryt", "citizen developer",
        "ai automation", "automation specialist", "automation consultant",
        "process automation", "workflow automation", "ai consultant", "ai solutions",
        "ai operations", "ai implementation", "prompt engineer", "ai enablement",
        "technical support engineer", "product specialist",
    ],
    adzuna_queries=[
        "implementation consultant remote",
        "business analyst low-code remote",
        "AI automation specialist remote",
        "solutions engineer remote",
        "low-code developer remote",
        "citizen developer remote",
        "Power Platform consultant remote",
    ],
    jsearch_queries=[
        "implementation consultant low-code no-code remote",
        "low-code developer Mendix OutSystems Power Apps remote Europe",
        "AI automation specialist n8n remote",
    ],
    remoteok_tags=["consulting", "automation", "customer-success", "ai"],
    remotive_categories=["customer-support", "product", "business", "all-others"],
    exclude={"intern", "staz", "praktykant", "junior", "sales", "account executive", "recruiter",
             "test automation", "qa automation", "qa engineer", "tester", "test engineer",
             "quality assurance", "sdet", "qa ",
             # very high seniority only; "senior" is NOT excluded (the owner confirmed senior BA offers,
             # 2026-10-25) — years of experience are judged from the description instead
             "principal", "lead", "expert", "architect", "head of", "manager", "director"},
)

# Software implementation / onboarding / training roles: knows the system, configures it for the client, trains
# the client's people (Polish and English titles). Added 2026-10-25: the Consulting profile mostly returned
# Business Analyst roles, which are a different job.
IMPLEMENTATION = Profile(
    name="Implementation",
    sheet="Wdrozenia",
    keywords=[
        "wdrożeniowiec", "wdrożeniowy", "konsultant wdrożeniowy", "specjalista ds. wdrożeń", "specjalista wdrożeń",
        "inżynier wdrożeń", "specjalista ds. szkoleń", "trener", "opiekun klienta", "konsultant systemów",
        "konsultant ds. wdrożeń", "ds. wdrożeń", "wdrożenia oprogramowania",
        "implementation consultant", "implementation specialist", "implementation engineer", "implementation manager",
        "customer onboarding", "onboarding specialist", "onboarding manager", "onboarding consultant",
        "technical trainer", "software trainer", "training specialist", "learning specialist", "enablement specialist",
        "application specialist", "application consultant", "functional consultant", "solutions consultant",
        "professional services consultant", "professional services engineer", "customer success", "technical account manager",
        "deployment specialist", "deployment engineer", "go-live", "customer support engineer", "technical support specialist",
    ],
    adzuna_queries=[
        "wdrożeniowiec zdalnie",
        "specjalista ds. wdrożeń zdalnie",
        "konsultant wdrożeniowy remote",
        "implementation specialist remote",
        "customer onboarding specialist remote",
        "technical trainer remote",
    ],
    jsearch_queries=[
        "implementation specialist software remote Europe",
        "wdrożeniowiec oprogramowania praca zdalna",
    ],
    remoteok_tags=["customer-success", "support", "consulting", "training"],
    remotive_categories=["customer-support", "all-others", "product"],
    # Owner's choice: remote PLUS hybrid / on-site in the region (Koszalin, Szczecin, Tricity, Poznań)
    regional_where=["Koszalin", "Szczecin", "Gdańsk", "Poznań"],
    regional_queries=["wdrożeniowiec", "specjalista ds. wdrożeń", "konsultant ds. wdrożeń", "konsultant wdrożeniowy"],
    regional_cities=["koszalin", "szczecin", "gdańsk", "gdynia", "sopot", "trójmiasto", "poznań", "kołobrzeg"],
    exclude={"intern", "staz", "praktykant", "junior", "sales", "account executive", "recruiter",
             "principal", "lead", "expert", "architect", "head of", "manager", "director",
             "test automation", "qa automation", "qa engineer", "tester", "sdet"},
)

PROFILES = [QA, CONSULTING, IMPLEMENTATION]
