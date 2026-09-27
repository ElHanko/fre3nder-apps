# fre3nder-apps

Application package sources and release tooling for Fre3nder.

This repository is intentionally separate from the Fre3nder platform. The
platform verifies and installs `.fre3app` packages; this repository builds and
publishes them.

## Current scope

The repository contains:

- a deterministic `.fre3app` builder;
- a minimal `dummy` package used to qualify the format and lifecycle contract;
- the pinned Fluidd 1.37.6 web frontend recipe;
- host-side tests for reproducibility and package signatures.

No App Store is required. A `.fre3app` artifact can be installed directly by
file on a compatible Fre3nder system.

## Build

The builder never creates signing keys. Supply an existing Ed25519 private key:

```sh
scripts/build-fre3app   apps/dummy   --key <fre3nder-root>/local/production/keys/apps/private.pem
```

The output is written to `dist/` by default.

## Fluidd

Fluidd is a static web frontend with no daemon. Its entire web payload is
included in the signed `.fre3app`; the printer never downloads Fluidd and
Moonraker does not update its files. On the build host, prepare the pinned
upstream release before running the normal builder:

```sh
scripts/prepare-fluidd
scripts/build-fre3app apps/fluidd --key <signing-key>
```

`prepare-fluidd` downloads the exact v1.37.6 asset listed in
`apps/fluidd/upstream.json`, checks its size and SHA-256, safely extracts it
into ignored `apps/fluidd/payload/`, and validates `index.html` and
`release_info.json`. `--archive <file>` uses a previously downloaded archive
with the same checks. The builder signs every payload file in `SHA256SUMS`.

Fluidd's source commit, archive identity and GPL-3.0-only redistribution
information are recorded in `apps/fluidd/upstream.json` and
`apps/fluidd/licenses/UPSTREAM`. The package carries the GPL version 3 text in
`apps/fluidd/licenses/LICENSE.fluidd`.

## Trust

The official publisher id is `fre3nder-official`. The matching public trust
anchor is shipped by the Fre3nder platform. The private signing key must remain
outside this repository.

## License

Project-authored material is licensed under AGPL-3.0-or-later unless a file or
bundled third-party component states otherwise.
