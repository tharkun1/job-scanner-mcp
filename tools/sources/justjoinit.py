"""JustJoin.it — public API removed as of 2025. Source disabled.

JustJoin.it removed their public REST API (https://justjoin.it/api/offers returns 404).
Their site is now a React SPA requiring authentication for API access.
Polish IT jobs are covered by NoFluffJobs and Pracuj.pl in this scanner.
"""


def fetch(profile=None) -> list[dict]:
    print("  [JustJoin.it] Public API no longer available — skipped.")
    return []
