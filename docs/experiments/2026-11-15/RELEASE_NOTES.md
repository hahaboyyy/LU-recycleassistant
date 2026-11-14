# Repair evaluation 15 November 2026

The measured release uses 4096 output tokens, one bounded transient retry, and at most one additional visual identity check for eligible uncertain categories. A length-limited reply is reported as OUTPUT_LIMIT. Explicit supported-item corrections can replace a mistaken candidate. Demo explanations identify scripted responses accurately.

177 pytest checks and 11 backend checks passed locally. These are software checks, not image accuracy.

| Metric | Result | 90% threshold |
|---|---:|---|
| Usable initial recognition responses | 60/60 (100%) | Met |
| Photo-only exact IDs on clear supported images | 42/48 (87.5%) | Not met |
| Secondary reference-informed simulated users, clear IDs | 47/48 (97.9%) | Met under this assisted simulation |

The original three-arm primary comparison remains unchanged. Clear-item complete advice was 8/48 for the direct baseline and 42/48 for both integrated primary arms. Correct workflow action over all cases was 48/60, 51/60 and 53/60. A workflow action is not an item-identification score.

The secondary simulation adds reference-name answers to five questions that lack an original E fixture. It is not photo-only accuracy, a real-user study or an independent held-out test. The same images have been used to analyse repairs. No labels or images were changed, and no failed row was silently replaced.

Original run: formal60_2026-11-14. First repair: 58/60 usable, 43/48 clear IDs. Second repair: 60/60 usable, 42/48 clear IDs. All remain archived locally. Release raw responses contain 126 HTTP requests, including six identity-review requests; primary interactive rows reuse the initial observation.

See summary.csv, per_case.csv, acceptance_results.json, assistance_summary.json and reference_assisted_replay.jsonl. Semantic advice ratings are assistant assessments with explicit reasons and still require the team's review. Source snapshots and image hashes are retained.

The public Render service has not been reconfigured or re-accepted by this local experiment. See DEPLOYMENT.md for the live environment and validation steps. The backup recording and physical presentation-device check remain team tasks.
