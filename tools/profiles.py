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
    exclude: set[str] = field(default_factory=lambda: {"intern", "staz", "praktykant"})  # "junior" allowed since 2026-11-10
    use_pracuj: bool = False        # pracujwit.pl RSS is a testing-only category feed
    regional_where: list[str] = field(default_factory=list)    # cities searched on Adzuna PL (on-site / hybrid roles near home)
    regional_queries: list[str] = field(default_factory=list)  # what to search for in those cities
    regional_cities: list[str] = field(default_factory=list)   # lower-case city names accepted from NoFluffJobs even if not fully remote
    use_intl_dev: bool = False      # Impactpool and ReliefWeb (UN, World Bank, EU, NGO jobs); E-gov profile only
    intl_queries: list[str] = field(default_factory=list)      # search phrases for those two sources
    adzuna_countries: list[str] = field(default_factory=list)  # limit Adzuna remote searches to these countries (empty = all)
    skip_sources: list[str] = field(default_factory=list)      # source names from fetch_jobs.SOURCES not used for this profile
    hybrid_cities: list[str] = field(default_factory=list)     # cities outside the home region: only offers not marked as purely on-site, labelled 'do decyzji' (2026-11-16)
    office_in_region: bool = True   # SOLID.Jobs, RocketJobs, Praca.pl: keep on-site offers in regional_cities (False: only remote / hybrid there), 2026-11-26
    hybrid_elsewhere: bool = True   # SOLID.Jobs, RocketJobs, Praca.pl: keep hybrid offers outside the region with a "check the office days" note, 2026-11-26
    solid_divisions: list[str] = field(default_factory=lambda: ["it"])  # SOLID.Jobs sections read (2026-11-26: "sales", "marketing", "other" for profiles outside IT)
    use_pl_general_boards: bool = False  # RocketJobs.pl and Praca.pl (non-IT boards), for profiles outside IT (2026-11-26)
    rocket_categories: list[str] = field(default_factory=list)  # RocketJobs: keep only these address categories (empty = all)
    exclude_lifted_by: dict[str, set[str]] = field(default_factory=dict)  # exclude word -> title words that cancel it (empty = none), 2026-11-27

    def __post_init__(self):
        self.patterns = compile_patterns(self.keywords)

    def matches(self, title: str) -> bool:
        return any(p.search(title) for p in self.patterns)

    def excluded(self, title: str) -> bool:
        low = title.lower()
        return any(kw in low and not any(w in low for w in self.exclude_lifted_by.get(kw, ())) for kw in self.exclude)


QA = Profile(
    name="QA",
    use_pl_general_boards=True,   # Praca.pl and RocketJobs.pl for the owner too (2026-11-26, after the test: regional implementation offers)
    rocket_categories=["consulting-", "support-it", "it-i-telekomunikacja", "programowanie", "testowanie", "analiza"],
    sheet="Testing",
    keywords=[
        "qa", "quality assurance", "test automation", "playwright", "sdet",
        "tester", "qa engineer", "test engineer", "automated testing",
        "selenium", "cypress", "automation engineer", "quality engineer",
        # manual testing (the owner 2026-11-12: "I am first of all a manual tester")
        "manual tester", "manual qa", "software tester", "qa tester", "test analyst", "qa specialist",
        "tester manualny", "tester oprogramowania", "testerka", "specjalista ds. testów", "analityk testów",
        # Polish titles without the word "tester" (e.g. "Specjalista ds. testowania systemów sklepowych" was lost
        # in the pracuj.pl e-mail import as "matches no profile", 2026-11-27)
        "testowania", "testowanie", "testów", "jakości oprogramowania", "jakości systemów informatycznych",
    ],
    adzuna_queries=[
        "QA automation remote",
        "Playwright QA remote",
        "manual tester remote",
        "software tester remote",
        "tester manualny zdalnie",
        "tester oprogramowania zdalnie",
    ],
    # JSearch defaults to the US; "@pl" = search in Poland (country parameter). 200 requests/month for all profiles.
    jsearch_queries=[],  # JSearch off: no Polish/EU results (tested 2026-11-13)
    remoteok_tags=["qa-engineer", "testing", "sdet"],
    remotive_categories=["qa", "testing", "software-dev"],
    use_pracuj=True,
    # hybrid / on-site testing jobs in the owner's region (2026-11-12), as in the Implementation profile
    regional_where=["Koszalin", "Szczecin", "Gdańsk", "Poznań"],
    regional_queries=["tester", "tester oprogramowania", "QA"],
    regional_cities=["koszalin", "szczecin", "gdańsk", "gdynia", "sopot", "trójmiasto", "poznań", "kołobrzeg"],
    # senior automation roles are a barrier for the owner; unreadable US pages let them through (2026-11-12)
    exclude={"intern", "staz", "praktykant", "senior", "sr.", "sr ", "lead", "principal", "staff ", "architect",
             "head of", "manager", "director", "expert",
             "monter", "montaż", "elektryk", "produkcj"},  # factory "assembler / tester" jobs from the city searches
    # "Senior Manual Tester" / "Senior Tester Manualny" pass, like "Starszy tester manualny" already did;
    # senior automation stays out (the owner, 2026-11-27). Years of experience are judged from the description.
    exclude_lifted_by={k: {"manual"} for k in ("senior", "sr.", "sr ")},
)

# Implementation / consulting / AI-automation roles that fit: no-code platform logic,
# client contact, training, troubleshooting, working with AI agents (MCP).
CONSULTING = Profile(
    name="Consulting",
    use_pl_general_boards=True,   # Praca.pl and RocketJobs.pl for the owner too (2026-11-26, after the test: regional implementation offers)
    rocket_categories=["consulting-", "support-it", "it-i-telekomunikacja", "programowanie", "testowanie", "analiza"],
    sheet="Consulting",
    keywords=[
        "implementation consultant", "implementation specialist", "implementation engineer",
        "solutions engineer", "solutions consultant", "solution consultant", "solutions architect",
        "technical consultant", "functional consultant", "business analyst", "systems analyst",
        "customer success engineer", "technical account manager", "technical trainer",
        "forward deployed engineer", "integration specialist", "integration engineer",
        # low-code / no-code titles moved to the LOWCODE profile (own tab 'low-code', 2026-11-10)
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
    jsearch_queries=[],  # JSearch off: no Polish/EU results (tested 2026-11-13)
    remoteok_tags=["consulting", "automation", "customer-success", "ai"],
    remotive_categories=["customer-support", "product", "business", "all-others"],
    exclude={"intern", "staz", "praktykant", "sales", "account executive", "recruiter",
             "test automation", "qa automation", "qa engineer", "tester", "test engineer",
             "quality assurance", "sdet", "qa ",
             # very high seniority; senior BA titles are excluded too (the owner, 2026-11-10: BA at mid level only).
             # Other "senior" titles stay: years of experience are judged from the description instead.
             "principal", "lead", "expert", "architect", "head of", "manager", "director",
             "senior business", "sr business", "sr. business", "senior it business", "senior systems analyst",
             "senior analyst", "starszy analityk"},
)

# Software implementation / onboarding / training roles: knows the system, configures it for the client, trains
# the client's people (Polish and English titles). Added 2026-10-25: the Consulting profile mostly returned
# Business Analyst roles, which are a different job.
IMPLEMENTATION = Profile(
    name="Implementation",
    use_pl_general_boards=True,   # Praca.pl and RocketJobs.pl for the owner too (2026-11-26, after the test: regional implementation offers)
    rocket_categories=["consulting-", "support-it", "it-i-telekomunikacja", "programowanie", "testowanie", "analiza"],
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
        # IT / field technician roles (the owner 2026-11-18: electrician 2020-2021, Acer service, electronics technician;
        # mobile work with travel accepted after the EXORIGO-UPOS application)
        "technik it", "technik informatyk", "technik wdrożeń", "zespołu wdrożeń", "technik serwisu",
        "serwisant", "serwisantka", "technik serwisant", "field service", "field technician",
        "wsparcia technicznego", "mobilny inżynier",
    ],
    adzuna_queries=[
        "wdrożeniowiec zdalnie",
        "specjalista ds. wdrożeń zdalnie",
        "konsultant wdrożeniowy remote",
        "implementation specialist remote",
        "customer onboarding specialist remote",
        "technical trainer remote",
    ],
    jsearch_queries=[],  # JSearch off: no Polish/EU results (tested 2026-11-13)
    remoteok_tags=["customer-success", "support", "consulting", "training"],
    remotive_categories=["customer-support", "all-others", "product"],
    # the owner's choice (2026-10-25): remote PLUS hybrid / on-site in the region (Koszalin, Szczecin, Tricity, Poznań)
    regional_where=["Koszalin", "Szczecin", "Gdańsk", "Poznań"],
    regional_queries=["wdrożeniowiec", "specjalista ds. wdrożeń", "konsultant ds. wdrożeń", "konsultant wdrożeniowy",
                      "technik IT", "serwisant IT", "technik wdrożeń"],  # plain "serwisant" = mostly HVAC/cars (283 hits on pracuj.pl)
    regional_cities=["koszalin", "szczecin", "gdańsk", "gdynia", "sopot", "trójmiasto", "poznań", "kołobrzeg"],
    exclude={"intern", "staz", "praktykant", "sales", "account executive", "recruiter",
             "principal", "lead", "expert", "architect", "head of", "manager", "director",
             "test automation", "qa automation", "qa engineer", "tester", "sdet"},
)

# E-government and international development consulting (the owner, 2026-11-13): his rarest asset is
# 4+ years of digitising business registration for six governments at the UN. Consultancies and roles at
# the UN, World Bank, EU, donors and consulting firms; many are home-based contracts.
EGOV = Profile(
    name="EGov",
    sheet="E-gov",
    keywords=[
        "e-government", "egovernment", "e-governance", "digital government", "digital public", "digital services",
        "e-services", "eservices", "e-registration", "eregistration", "business registration", "company registration",
        "business facilitation", "trade facilitation", "business environment", "registry", "registries", "one-stop",
        "single window", "govtech", "public service delivery", "digital transformation", "digital id", "digital identity",
        "digitalization", "digitalisation", "e-procurement", "investment climate", "regulatory reform",
    ],
    adzuna_queries=["e-government consultant remote", "digital government consultant remote"],
    jsearch_queries=[],
    remoteok_tags=[],
    remotive_categories=[],
    use_intl_dev=True,
    intl_queries=["e-government", "digital government", "business registration", "e-registration",
                  "business environment reform", "trade facilitation", "digital public infrastructure", "e-services"],
    exclude={"intern", "internship", "trainee", "traineeship", "driver", "clerk", "assistant", "national consultan",
             "director", "chief", "head of", "principal", "android", "ios ", "mobile developer"},
)

PROFILES = [QA, CONSULTING, IMPLEMENTATION, EGOV]

# Low-code / no-code platforms (the owner, 2026-11-10: "w tego typu firmach upatruję swoich największych szans").
# NOT in PROFILES: it is run daily by tools/lowcode_watch.py, which writes to the 'low-code' tab (own columns)
# and notifies him (dashboard box, Windows popup, e-mail). "developer" titles are kept on purpose:
# a low-code "developer" is mostly a configurator, which is the owner's own platform work.
LOWCODE_COMPANIES = [  # offers from these companies are taken whatever the title (except the excludes)
    "domdata", "consdata", "eximee", "madkom", "asseco data systems", "webcon", "astrafox", "amodit",
    "bosflow", "eleader", "productive24", "netcompany", "nortal", "camunda", "unqork", "creatio", "bizagi",
    "bonitasoft", "betty blocks", "mendix", "outsystems", "appian", "kissflow", "nintex", "processmaker", "joget",
]
LOWCODE = Profile(
    name="LowCode",
    sheet="low-code",
    keywords=[
        "low-code", "low code", "lowcode", "no-code", "no code", "nocode", "citizen developer",
        "ferryt", "webcon", "amodit", "eximee", "bosflow", "productive24", "koliber",
        "mendix", "outsystems", "power platform", "power apps", "powerapps", "power automate",
        "appian", "pega", "pegasystems", "camunda", "creatio", "bizagi", "bonita", "nintex", "kissflow",
        "unqork", "betty blocks", "joget", "processmaker", "flowable", "servicenow app engine",
        "bpm", "bpms", "workflow", "obieg dokumentów", "ezd", "konfigurator", "configurator",
        "process automation", "automatyzacja procesów", "form builder", "formularzy elektronicznych",
    ],
    adzuna_queries=["low-code", "no-code", "Ferryt", "WEBCON", "BPM workflow konsultant"],
    jsearch_queries=[],  # JSearch off: no Polish/EU results (tested 2026-11-13)
    remoteok_tags=["no-code", "low-code"],
    remotive_categories=["all-others", "customer-support", "product"],
    regional_where=["Koszalin", "Szczecin", "Gdańsk", "Poznań", "Warszawa"],
    # Warszawa (2026-11-16): the owner accepts some trips (e.g. a week a month in the office) -> hybrid offers shown for his decision
    hybrid_cities=["Warszawa"],
    regional_queries=["low-code", "workflow"],
    regional_cities=["koszalin", "szczecin", "gdańsk", "gdynia", "sopot", "trójmiasto", "poznań", "kołobrzeg"],
    exclude={"intern", "staz", "staż", "praktykant", "sales", "account executive", "account manager", "recruiter",
             "sprzedaż", "sprzedaży", "handlow",  # Polish sales titles (the owner 2026-11-16: "nie jestem sprzedawcą")
            
             "handlowiec", "przedstawiciel", "principal", "head of", "director", "dyrektor", "kierownik",
             "ux/ui", "ux designer", "ui designer", "graphic",
             # levels he cannot defend in an interview (rule 2026-11-10) and a required foreign language
             "senior", "sr.", "sr ", "lead", "architect", "starszy", "forward deployed",
             "german", "niemiecki", "french", "dutch"},
)
