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
python3 scripts/stage_fre3app.py apps/dummy --output local/dummy/package
scripts/build-fre3app local/dummy/package \
  --key <fre3nder-root>/local/production/keys/apps/private.pem
```

The output is written to `dist/` by default.

Recipe directories are not package sources. App preparers assemble explicit,
keyless package sources under ignored `local/<app>/package/`; only these are
passed to the builder. See [package staging](docs/package-staging.md) for the
file inventory, migration and host regression tests.

Alternative upstream and dependency inputs can be supplied directly to existing
preparers without editing recipes. Changed inputs use separate cache/output
namespaces unless an explicit output is supplied. The generic builder accepts
stable `--version VERSION --release-serial N` together (`N >= 1`), or the existing
`--develop --version VERSION` with serial zero. No version or serial is allocated
automatically. See [selected-input examples](docs/package-staging.md#selected-build-inputs)
and [release metadata](docs/package-layout.md#release-metadata). Builds and signing
still require the applicable operator authorization.

## Fluidd

Fluidd is a static web frontend with no daemon. Its entire web payload is
included in the signed `.fre3app`; the printer never downloads Fluidd and
Moonraker does not update its files. On the build host, prepare the pinned
upstream release before running the normal builder:

```sh
apps/fluidd/scripts/prepare-fluidd
scripts/build-fre3app local/fluidd/package --key <signing-key>
```

`prepare-fluidd` downloads the exact v1.37.6 asset listed in
`apps/fluidd/upstream.json`, checks its size and SHA-256, safely extracts it
into `local/fluidd/package/payload/`, and validates `index.html` and
`release_info.json`. `--archive <file>` uses a previously downloaded archive
with the same checks. The builder signs every payload file in `SHA256SUMS`.
`--upstream FILE` selects another official Fluidd release definition. Its exact
bytes are staged, and the service checks the payload against that selected
version. Commit-only source builds are not supported.

Fluidd's source commit, archive identity and GPL-3.0-only redistribution
information are recorded in `apps/fluidd/upstream.json` and
`apps/fluidd/licenses/UPSTREAM`. The package carries the GPL version 3 text in
`apps/fluidd/licenses/LICENSE.fluidd`.

## Fre3nderScreen

Build the release package from an existing neutral Fre3nder X2000 app artifact
and an existing Ed25519 key:

```sh
apps/fre3nderscreen/scripts/build-fre3nderscreen-release \
  --artifact <fre3nder-app-artifact-dir> --key <signing-key>
```

The wrapper calls the release importer, replaces the prepared Fre3nderScreen
package source after validation, and calls the generic package builder. It
reports the resulting package path and SHA-256 and performs no cross-build or
deployment. The underlying
`prepare-fre3nderscreen` and `build-fre3app` commands are described in the
[recipe documentation](docs/fre3nderscreen-recipe.md).

## OctoApp

OctoApp is packaged as an isolated autostart application. Fre3nder does not run
OctoApp's upstream installer and does not add OctoApp-specific Python packages
to the RootFS.

For the normal build, use the OctoApp build wrapper:

```sh
apps/octoapp/scripts/build-octoapp
```

By default it uses the sibling `../fre3nder` checkout for:

- the Fre3nder X2000 Buildroot output;
- the official app signing key.

The paths can be overridden explicitly when required:

```sh
apps/octoapp/scripts/build-octoapp \
  --buildroot-output <buildroot-output> \
  --key <signing-key>
```

The normal build reuses the already prepared native pycryptodomex bundle and
the reviewed pure-Python dependency lock.

To rebuild the native pycryptodomex dependency before packaging:

```sh
apps/octoapp/scripts/build-octoapp --refresh-native
```

To deliberately regenerate the pure-Python dependency lock:

```sh
apps/octoapp/scripts/build-octoapp --refresh-lock
```

Both refresh operations can be requested together:

```sh
apps/octoapp/scripts/build-octoapp --refresh-native --refresh-lock
```

A custom output path can be supplied with:

```sh
apps/octoapp/scripts/build-octoapp --output <package.fre3app>
```

The wrapper orchestrates the existing OctoApp build tools. It does not
automatically change the pinned upstream version, upstream commit,
`release_serial`, or package version. Those changes remain explicit review
steps.

The individual tools remain available for development and debugging:

```sh
apps/octoapp/scripts/lock-octoapp

apps/octoapp/scripts/build-octoapp-native \
  --buildroot-output <fre3nder-root>/local/production/work/x2000/buildroot-output-fre3nder

apps/octoapp/scripts/prepare-octoapp \
  --buildroot-output <fre3nder-root>/local/production/work/x2000/buildroot-output-fre3nder

scripts/build-fre3app local/octoapp/package --key <signing-key>
```

`prepare-octoapp` checks out the exact upstream commit from
`apps/octoapp/upstream.json`, applies the narrow Fre3nder integration patch,
downloads only the hash-locked universal wheels, stages Pillow from the
Fre3nder Buildroot output, and stages the app-local pycryptodomex bundle
produced by `build-octoapp-native`. The resulting payload contains OctoApp,
all application Python dependencies and runtime metadata.

`--upstream FILE` and `--lock FILE` select another source pin and universal-wheel
lock; `--requirements FILE` supplies the corresponding requirements when they
differ. The lock must match those requirements. Python 3.12, the existing
integration patch and the maintained native dependency definitions remain gates.
`--source DIR` requires a clean checkout at the selected commit; `--wheel-dir DIR`
allows offline wheel input. The staged metadata describes those selected inputs.
Preparation needs no publisher key and does not start a native build. The native
builder now mounts a temporary selection of tracked platform inputs read-only,
using the platform's `x2000-build-input-sha256 --snapshot` interface. It does not
mount the platform checkout or its production key directories. The existing
Buildroot work tree remains writable; host tools from that tree and the later
signing boundary still require separate isolation work. Native bundle overrides
remain separate work.

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
