# Package source layout

App preparers assemble a separate package source directory; never pass a recipe
directory containing development tools to the builder. See
[the staging contract and per-app inventory](package-staging.md).

Each prepared package source directory contains:

```text
manifest.toml.in
service
payload/
licenses/          # when required
```

`manifest.toml.in` is the signed manifest template. It must contain the literal
token:

```text
@PUBLISHER_FINGERPRINT@
```

exactly once. `scripts/build-fre3app` replaces that token with the SHA-256
fingerprint of the DER SubjectPublicKeyInfo derived from the supplied Ed25519
private key.

The builder then creates:

```text
manifest.toml
service
payload/...
licenses/...
SHA256SUMS
SHA256SUMS.sig
```

The archive is a ZIP container using stored members, fixed timestamps, fixed
modes, and sorted member order so identical inputs and the same signing key
produce byte-identical output.

## Release metadata

Without options the builder uses the version and release serial from the template
unchanged. Two explicit modes render only `[app].version` and
`[app].release_serial` in memory, then use the same manifest validation, checksums,
Ed25519 signing and deterministic ZIP implementation:

```sh
# Development: version must contain -fre3nder.0.; serial is always zero.
scripts/build-fre3app <package-source> --key <existing-key> \
  --develop --version <unique-development-version>

# Stable override: both fields are required; serial must be an integer >= 1.
scripts/build-fre3app <package-source> --key <existing-key> \
  --version <reviewed-stable-version> --release-serial 5
```

`--version` alone for a stable build, `--release-serial` alone, zero/negative
stable serials, or combining `--develop` with `--release-serial` are errors.
All versions must match `[A-Za-z0-9][A-Za-z0-9.+_-]*` and remain at most 128
characters long. Invalid override and template versions are rejected before
accessing the signing key.
The template, publisher identity, target and signature contract are not edited.
Default builder inputs still produce the same archive bytes. Updated service
code or selected upstream inputs do change package contents; do not republish
such contents under an existing release identity. This tool has no serial ledger
or automatic allocation: the operator must select an unused version and
appropriate increasing serial. Signing requires separate operator authorization.

Files under `payload/bin/` are installed executable with mode 0755.
Other payload files are installed with mode 0644. The platform extracts both
from the verified signed archive.

An optional `[web] frontend = true` declares a static web frontend. Such a
package must contain a nonempty `payload/index.html`; the platform serves its
signed payload at `/opt/fre3nder/apps-v2/<app>/payload`. A missing `[web]`
section means the package is not a web frontend. The platform owns frontend
selection and Lighttpd refresh, while the app service remains unprivileged.
