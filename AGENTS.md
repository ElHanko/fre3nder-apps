# Scope

This repository contains Fre3nder application package sources and tooling for
building signed `.fre3app` artifacts.

# Working rules

- KISS: prefer the smallest implementation that proves or delivers the current goal.
- Do not commit or push unless the operator explicitly authorizes it.
- Do not publish GitHub Releases unless explicitly authorized.
- Do not generate or rotate signing keys from this repository.
- Never commit private keys, tokens, credentials, or other secrets.
- Finished `.fre3app` artifacts belong in `dist/` locally and GitHub Releases
  when published; they are not committed to Git.
- Package sources must be reproducible from tracked repository inputs plus an
  explicitly supplied signing key.
- Every bundled third-party component must have documented provenance and
  redistribution status before publication.
- Application lifecycle scripts must run without root privileges.
- Do not add platform policy or printer-specific privileged setup here; that
  belongs in the `fre3nder` platform repository.

# Package boundary

`fre3nder` owns the package format verifier, trust anchors, installer, recovery,
runtime, and platform CLI.

`fre3nder-apps` owns package recipes, reproducible package construction, release
metadata, and later repository-index generation.

# Validation before commit

At minimum:

1. `git status --short`
2. `git diff --check`
3. run the targeted host tests
4. review the complete diff
5. scan for secrets/private keys
6. verify third-party provenance and licensing
