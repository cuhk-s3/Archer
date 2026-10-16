# Review knowledge

`insights.jsonl` is the repository-visible, version-controlled projection of
verified knowledge collected by the reviewer. The SQLite database remains the
query store; on startup it imports this file so knowledge follows the repo.

Unverified hypotheses stay in SQLite and are available through explicit
`insight` searches, but are deliberately not exported or injected into later
reviews. Do not edit generated fingerprints by hand.
