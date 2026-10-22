# Fre3nder application repository (first stage)

A self-hosted, **opt-in** HTTP repository for existing, signed `.fre3app`
packages. Its Python worker imports authenticated packages from a local inbox,
creates a deterministic `index.json`, signs the exact index bytes with a
**separate Ed25519 repository key**, and exposes the public files through Nginx.

**Not implemented in this stage:** automatic upstream discovery/builds, mirrors,
package downloads, update notifications, and installation. The optional index
client is a separate [Fre3nder app](../apps/fre3nder-app-update/README.md).
Configured build modes are reserved for the subsequent stage and **do not
trigger builds**. The repository never re-signs `.fre3app` archives.

## Trust boundary

There are two independently trusted identities:

1. **Repository key**: signs `index.json`, with a detached raw 64-byte Ed25519
   signature in `index.json.sig`. The client must pin the repository public key,
   verify the signature on the exact index bytes, and remember the highest
   accepted `revision` to reject replay of older indices.
2. **App publisher key**: signs an individual `.fre3app` file. The publisher
   public key must also be trusted by the Fre3nder package core. Trusting a
   repository is **not** equivalent to trusting every package or publisher it
   references.

The worker checks imported `.fre3app` archives against the configured publisher
public key: SHA256SUMS coverage and hashes, the original Ed25519 package
signature, publisher ID and public-key fingerprint, app name, target platform,
and release identity. Package bytes are never changed. An existing installation
can only be updated normally with its original publisher ID/fingerprint;
signing an unofficial replacement with another key does not bypass that rule.

Private signing keys are **not** generated or rotated by this project. Supply
existing keys created and managed outside the repository. The worker reads an
existing repository private key; the existing app publisher **public** key is
sufficient for importing prebuilt packages. No app private key needs to enter
this first-stage container. Use different Ed25519 keys for publisher and index.

## Configuration and host setup

Run these commands from `docker-repository/` (adjust paths, users and mount
permissions for your machine):

```sh
mkdir -p local/secrets local/data/incoming local/data/public
cp config.example.toml local/config.toml
```

Provide pre-existing signing material at the locations named in the local
config, for example:

```text
local/secrets/repository-private.pem  # private, index signing
local/secrets/publisher-public.pem    # public, archive verification
```

The PEMs are externally supplied; no key generation is performed. Export the
repository **public** key outside this repository using OpenSSL's `pkey
-pubout` command and register/pin it in a future Fre3nder repository client.
Existing app publisher public keys are managed independently in Fre3nder.

Edit `local/config.toml`: specify repository name/key, publisher IDs/public
keys, and explicitly allowed app names. The `publisher` for each app must match
the identity in that app's signed manifest. A private operator can use their
already configured Fre3nder publisher; a third-party operator can publish only
apps explicitly assigned to their own publisher. Listing an app in the config
does not re-sign existing third-party packages.

For Linux bind mounts, `worker` runs as the unprivileged host UID/GID set in
`REPOSITORY_UID` and `REPOSITORY_GID` (defaults 1000:1000). That user must be
able to read `local/config.toml` and the required PEM files, and write
`local/data/`. Keep `local/secrets/` non-public and private PEMs readable only
by the chosen user. For example, create the data directory as that user;
for an existing root-owned data directory, adjust its ownership **only for the
repository data directory**, not for host system paths.

Set `REPOSITORY_BIND` and `REPOSITORY_PORT` in a local `.env` if necessary.
The default binds only to host `127.0.0.1:8088`; expose via a configured
HTTPS reverse proxy or explicitly opt in to LAN binding.

After explicit authorization to build the Docker image, start the server:

```sh
docker compose build worker
docker compose up -d
```

The worker runs one scan on startup, then every six hours by default. It only
scans the local incoming directory in this first stage; it does not contact
upstream repositories. You can run a one-shot scan inside the container:

```sh
docker compose exec worker python /opt/fre3nder-repository/repositoryd.py --once
```

The HTTP container serves **only** `local/data/public/` read-only. Neither
private PEMs nor the local config are mounted into Nginx.

## Adding a signed package

Write/transfer a complete `.fre3app` file to a temporary filename in
`local/data/incoming/`, then atomically rename it to a `*.fre3app` filename on
the same filesystem. This prevents the worker from reading an unfinished upload.
The next scan (or an explicit `--once`) verifies the package before publishing
it under `packages/<app>/`. A rejected package remains in `incoming/` for
operator inspection; remove or correct it to allow later scans to succeed.

The published layout is:

```text
index.json
index.json.sig
packages/
  <app>/
    <app>-<version>-<sha256-prefix>.fre3app
```

The signed JSON index uses schema `1` and includes a monotonically increasing
`revision`, a repository key fingerprint, and entries with app name, version,
release serial, publisher ID/fingerprint, target, channel, size, package SHA-256,
and relative download path. Versions are retained, not overwritten. An identity
conflict (same app/publisher and published release serial, or same development
version, with different bytes) is rejected.

Each index/signature file is replaced atomically. As the files are separate,
a concurrent HTTP client might briefly read a mismatched pair during a publish;
**clients must reject and retry a mismatched pair**, never bypass verification.
No new index is published when the package list/configuration is unchanged.

## Future build automation (not implemented)

Per app, `mode` will eventually select:

- `maintained`: use the versions explicitly pinned in `fre3nder-apps` recipes;
- `releases`: enumerate supported official upstream releases;
- `commits`: enumerate new commits on the configured upstream branch.

This requires app-specific recipe adapters for upstream locks, sources and
cross-build dependencies, plus per-app release serial allocation, a persistent
build history, testing and a separately authorized signing stage. The worker
must not mutate tracked recipes or expose publisher private keys to arbitrary
upstream build scripts. Mirror mode is intentionally deferred: it would copy
unaltered foreign signed packages and sign only its own repository index.

The optional `fre3nder-app-update` app checks an explicitly configured, trusted
index at startup, retries failures in the background, then checks every
approximately 30 minutes after success. With no configured URL and repository
public key it performs **no checks**. It persists verified package offers for
future Fre3nderScreen readers. Installed-version comparison, Screen integration,
package downloads and installations remain future work; installation must still
use the platform package core and its independent publisher verification.

## Developer validation

Syntax and unit tests do not build a Docker image or create signing keys:

```sh
python3 -m py_compile docker-repository/repositoryd.py
python3 -m unittest discover -s tests -p test_docker_repository.py -v
```

Before committing follow the root `AGENTS.md`: inspect Git status, run
`git diff --check`, review all diffs and test results, check for secrets and
host-specific data, and confirm third-party provenance. Do not commit, publish,
or launch Docker builds without the operator's explicit authorization.
