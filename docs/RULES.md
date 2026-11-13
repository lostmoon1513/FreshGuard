# Deterministic rules (M1)

Code: `backend/app/engine/rules/`. Pure functions: no LLM, no network, no clock (`now` is passed in).

## Terms
- **verified**: stance is `supports`/`contradicts` AND `integrity_ok is True`.
  Neutral, unchecked (`None`) and failed (`False`) evidence is ignored.
- **credible**: tier 1 or 2.
- **recent**: published within the claim's freshness window (inclusive). No window (static) = always recent.
  Undated evidence, or dated more than 1 day in the future, is "undated" and is never recent.
- **strong**: verified AND credible AND recent.

## Freshness windows
| Volatility | Window |
|---|---|
| fast | 30 days |
| slow | 365 days |
| static | none |

## Decision table (first matching row wins)
| # | Condition | Label | Reason |
|---|---|---|---|
| 1 | no verified evidence, static claim | fresh (conf 0.5) | static_not_checked |
| 2 | no verified evidence | unverifiable (conf 0) | no_verified_evidence |
| 3 | strong support AND strong contradiction | potentially_stale | credible_sources_conflict |
| 4 | strong contradiction | stale | credible_recent_contradiction |
| 5 | strong support | fresh | credible_recent_support |
| 6 | only weak evidence (tier 3, old or undated) | potentially_stale | only_weak_evidence |

## Confidence (how strongly evidence backs the chosen label)
- Evidence weight = tier weight (T1 0.9, T2 0.7, T3 0.35) x recency factor
  (1.0 inside the window; undated 0.5; decays linearly to 0.25 at 3x the window).
- Side score = noisy-or of that side's weights (corroboration raises it, never reaches 1).
- stale / fresh: own side score x (1 - opposing side score).
- potentially_stale: min(0.5, score of all verified evidence). unverifiable: 0.

## Answer level
Label = worst claim label (stale > potentially_stale > unverifiable > fresh; no claims = unverifiable).
Confidence: fresh = weakest claim (min); stale / potentially_stale = strongest claim with that label (max);
unverifiable = 0.

## Source tiers
1 = government (`.gov`, `gov.uk`, `gov.in`, `nic.in`, ...), `.int`, academic (`.edu`, `ac.uk`, `ac.in`, ...),
standards bodies (w3.org, ietf.org, iso.org, un.org, ...). 2 = a short list of major news/reference sites.
3 = everything else, unparseable URLs, non-http(s) schemes and IP hosts.