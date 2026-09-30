# Package source layout

Each package source directory contains:

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

Files under `payload/bin/` are installed executable with mode 0755.
Other payload files are installed with mode 0644. The platform extracts both
from the verified signed archive.

An optional `[web] frontend = true` declares a static web frontend. Such a
package must contain a nonempty `payload/index.html`; the platform serves its
signed payload at `/opt/fre3nder/apps-v2/<app>/payload`. A missing `[web]`
section means the package is not a web frontend. The platform owns frontend
selection and Lighttpd refresh, while the app service remains unprivileged.
