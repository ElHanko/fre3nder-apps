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
- the pinned OctoApp 3.2.4 local-Moonraker application recipe;
- host-side tests for reproducibility and package signatures.

No App Store is required. A `.fre3app` artifact can be installed directly by
file on a compatible Fre3nder system.

## Build

The builder never creates signing keys. Supply an existing Ed25519 private key:

```sh
scripts/build-fre3app apps/dummy \
  --key <fre3nder-root>/local/production/keys/apps/private.pem
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

## OctoApp

OctoApp is packaged as an isolated autostart application. Fre3nder does not run
OctoApp's upstream installer and does not add OctoApp-specific Python packages
to the RootFS.

For the normal build, use the OctoApp build wrapper:

```sh
scripts/build-octoapp
```

By default it uses the sibling `../fre3nder` checkout for:

- the Fre3nder X2000 Buildroot output;
- the official app signing key.

The paths can be overridden explicitly when required:

```sh
scripts/build-octoapp \
  --buildroot-output <buildroot-output> \
  --key <signing-key>
```

The normal build reuses the already prepared native pycryptodomex bundle and
the reviewed pure-Python dependency lock.

To rebuild the native pycryptodomex dependency before packaging:

```sh
scripts/build-octoapp --refresh-native
```

To deliberately regenerate the pure-Python dependency lock:

```sh
scripts/build-octoapp --refresh-lock
```

Both refresh operations can be requested together:

```sh
scripts/build-octoapp --refresh-native --refresh-lock
```

A custom output path can be supplied with:

```sh
scripts/build-octoapp --output <package.fre3app>
```

The wrapper orchestrates the existing OctoApp build tools. It does not
automatically change the pinned upstream version, upstream commit,
`release_serial`, or package version. Those changes remain explicit review
steps.

The individual tools remain available for development and debugging:

```sh
scripts/lock-octoapp

scripts/build-octoapp-native \
  --buildroot-output <fre3nder-root>/local/production/work/x2000/buildroot-output-fre3nder

scripts/prepare-octoapp \
  --buildroot-output <fre3nder-root>/local/production/work/x2000/buildroot-output-fre3nder

scripts/build-fre3app apps/octoapp --key <signing-key>
```

`prepare-octoapp` checks out the exact upstream commit from
`apps/octoapp/upstream.json`, applies the narrow Fre3nder integration patch,
downloads only the hash-locked universal wheels, stages Pillow from the
Fre3nder Buildroot output, and stages the app-local pycryptodomex bundle
produced by `build-octoapp-native`. The resulting payload contains OctoApp,
all application Python dependencies and runtime metadata.

On the printer the package service creates a pip-free isolated environment under
the app data directory. It uses `include-system-site-packages = false`; no
package resolver, compiler, Git checkout, `apt`, or `opkg` is used on the
printer. OctoApp's own Moonraker Git updater and allowed-service integration are
removed from the packaged Moonraker runtime so `.fre3app` remains the only
update and lifecycle path.

The upstream optional `pycryptodome` feature is provided as app-local
`pycryptodomex` 3.21.0. It is cross-built through the Fre3nder Buildroot
toolchain and staged only into the `.fre3app`; it is not installed into the
RootFS.

## Trust

The official publisher id is `fre3nder-official`. The matching public trust
anchor is shipped by the Fre3nder platform. The private signing key must remain
outside this repository.

## License

Project-authored material is licensed under AGPL-3.0-or-later unless a file or
bundled third-party component states otherwise.
