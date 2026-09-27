# fre3nder-apps

Application package sources and release tooling for Fre3nder.

This repository is intentionally separate from the Fre3nder platform. The
platform verifies and installs `.fre3app` packages; this repository builds and
publishes them.

## Current scope

The initial repository contains:

- a deterministic `.fre3app` builder;
- a minimal `dummy` package used to qualify the format and lifecycle contract;
- host-side tests for reproducibility and package signatures.

No App Store is required. A `.fre3app` artifact can be installed directly by
file on a compatible Fre3nder system.

## Build

The builder never creates signing keys. Supply an existing Ed25519 private key:

```sh
scripts/build-fre3app   apps/dummy   --key <fre3nder-root>/local/production/keys/apps/private.pem
```

The output is written to `dist/` by default.

## Trust

The official publisher id is `fre3nder-official`. The matching public trust
anchor is shipped by the Fre3nder platform. The private signing key must remain
outside this repository.

## License

Project-authored material is licensed under AGPL-3.0-or-later unless a file or
bundled third-party component states otherwise.
