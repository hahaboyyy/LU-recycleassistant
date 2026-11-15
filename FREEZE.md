# Frozen version frozen-2026-11-15

The user approved freezing the current implementation on 15 November 2026.
This freeze adds metadata, verification evidence, updated reproduction instructions
and the explicitly authorized temporary public demo credential. It does not change
application code, prompts, rules, images, reference labels or existing results.

The inference and evaluation files are unchanged from commit `46de9da4c8dac53bd270d634799384d1554c9bb6`.
`freeze/2026-11-15/files.sha256.csv` records 170 frozen files: 169 base repository paths plus the public demo `.env`, including
their SHA-256 and Git blob IDs. Text representation notes account for Git's
line-ending conversion; binary files are checked byte for byte. Only the base
`README.md` was revised to explain the included demo credential. The new freeze
metadata is anchored by the new commit and the `freeze/2026-11-15` branch.

## Fixed configuration

- Requested model: `deepseek-v4-flash-vision-exp`; endpoint: `https://api.deepseek.com/v1`.
- Output budget: 4096 tokens; temperature: 0.0.
- Provider read timeout: 15.0 seconds; transient retries: 1.
- JSON mode: True; strict scope: False.
- Image cap: 1280 pixels; JPEG quality: 85.
- Live backend: `integration:create_live_backend`; UI timeout: 35 seconds.
- Clarification limit: two rounds; evaluation seed: 521.
- Existing bounded identity-review behaviour is preserved unchanged.

The full settings are in `freeze/2026-11-15/runtime_config.json`. The root `.env` already contains these
settings and the authorized temporary shared API key; do not overwrite it with
an empty template. `runtime.env.example` remains a key-free configuration template. Shell or
server environment overrides must also match. The provider can change hosted
weights behind an alias; record the served model name during each experiment.

## Verification and use

The freeze validation passed 177 pytest checks and 11 backend checks. Logs and
the validated Python/package versions are retained in `freeze/2026-11-15`. This validation
did not rerun the visual experiment or test a physical camera/public deployment.

Use the exact frozen commit or the `freeze/2026-11-15` branch for experiments.
Run `python freeze/2026-11-15/verify.py` to check the files; add `--check-config` to compare
the non-secret live configuration. The included `.env` supplies the demo credential.

After freeze, record measured successes, errors and abstentions without changing
prompts, code, scoring or settings to reach a percentage. If a reproducible
program defect requires a change, create a new version and retain the old run.
The existing 60-case set has already influenced development: it can support
clearly labelled same-set evaluation, not a claim of an unseen independent test.
Reference-informed simulated-user results remain separate from photo-only results.

## Temporary public demo credential

The owner explicitly confirmed that this public repository should include the
project API key so everyone can test the application during the presentation
period. The root `.env` contains only the required project credential and frozen
runtime settings. Other private settings, local environments, caches and transient
logs are excluded. Historical tracked reports and results are preserved unchanged.

After the presentation, revoke the key at the API provider. Deleting `.env` from
the current branch does not invalidate a key already obtained from Git history.
Key revocation will intentionally end shared live access; future users must
supply a new valid credential.

## Direct live test on Windows

From the project directory, keep the supplied `.env` and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\Start-Demo.ps1 -Live -Port 8502
```

Open http://127.0.0.1:8502, upload a photo, and select **Identify item**.
A working network connection and an active provider credential are required.
