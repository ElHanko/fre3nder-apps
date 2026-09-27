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
