# Optional repository index discovery

`fre3nder-app-update` is an optional, unprivileged `.fre3app`. It retrieves and
verifies `index.json` and `index.json.sig` from one explicitly configured source.
It exposes authenticated **offers**, without comparing installed versions,
downloading packages, installing anything, or contacting Management API.
An offer is not a determination that an installed app needs an update.

## Preparation

```sh
apps/fre3nder-app-update/scripts/prepare-fre3nder-app-update
# Only after separate signing authorization, with an existing publisher key:
scripts/build-fre3app local/fre3nder-app-update/package --key <publisher-private-key>
```

The preparer copies only the manifest, service, `payload/client.py` and the
repository's AGPL-3.0-or-later license text. It uses the existing `package_stage`
operation and needs no key, network or build tools. The client is first-party
Fre3nder code; Python and OpenSSL are provided by the platform. No third-party
Python dependencies or binaries are bundled. There is no app-specific signer.

## Operator configuration

The package core supplies `FRE3NDER_APP_DATA_DIR`. Its normal persistent location
is `/home/fre3nder/.local/share/fre3nder-app-update/`. Create `repository.json`
there, readable by the existing `fre3nder` app user:

```json
{
  "base_url": "https://repository.example.invalid/",
  "public_key": "repository-public.pem"
}
```

Place the **existing repository Ed25519 public key** in the named file. Relative
key paths are resolved against this app data directory; absolute paths are also
accepted. No key, source or trust identity is selected, generated or downloaded
automatically. Repository keys are independent of `.fre3app` publisher keys and
do not add publisher trust to Package-Core. Never place a private key in this
configuration or package.

Missing configuration or missing/empty fields disable checks without an error
or network access. Malformed complete configuration, unreadable keys and invalid
keys are reported in status without a request. Configuration is reread every
check, so opting in does not require a restart. HTTP and HTTPS are supported;
HTTPS uses the standard certificate checks. URLs with credentials, queries or
fragments and HTTP redirects are rejected; environment proxy settings are not
used. Configure the final public repository URL explicitly.

The daemon checks immediately, every approximately 30 minutes after success,
and every minute while disabled or after failure, including an unavailable
network. A signature mismatch permits one additional retrieval of both files,
after one second, to handle the worker's separate atomic publications. No result
is accepted without a valid signature. HTTP requests have a 10-second socket
timeout, a 30-second response-body deadline, a 1 MiB index limit and a 64-byte
signature limit. OpenSSL subprocesses also have a 10-second timeout.

## Persistent output, schema 1

- `verified.json` is the authoritative, atomically replaced accepted state. It
  contains `schema`, `key_fingerprint`, `index` (the **exact UTF-8 index text**,
  JSON-escaped, not reserialized), `signature` (128 hex characters) and
  `checked_at` (UTC ISO 8601). The signed index itself carries the revision,
  repository identity and package list. Embedding it in one file commits the
  index and highest accepted revision together. Failed requests, validation or
  replacement leave the previous accepted state intact.
- `status.json` is a separately, atomically replaced summary for future Screen
  readers. It contains `schema`, `configuration` (`unconfigured`, `configured`
  or `invalid`), `check` (`disabled`, `ok` or `error`), nullable `error`,
  `repository` (name, key fingerprint and configured base URL), nullable
  `revision`, `last_attempt`, `last_success` (UTC ISO 8601) and `packages`.
  Each package includes `name`, `version`, `release_serial`, `publisher`
  (`id`, `key_fingerprint`), `channel`, `target` (`platform`, `arch`), `sha256`,
  `size` and `path`. Failed downloads or index validation retain the previous
  offers for the same readable configured key, with their original successful
  check time. Disabled, invalid or changed-key sources expose no offers.
- `client.pid` and `client.lock` support the local process lifecycle. They are
  not platform package state.

The summary can lag the authoritative state if its write is interrupted. Readers
must tolerate absent files and inspect `check` and `last_success` for freshness.
All files are private app data, readable by Screen under the same existing app
UID. No permission changes to platform state or sockets are needed.

The fingerprint is SHA-256 over Ed25519 DER SubjectPublicKeyInfo, matching the
worker and package contracts. Schema, revision, publisher and package identities,
release serials, channel, current X2000/MIPS target, size and SHA-256 are checked.
Package paths must match the existing worker's relative
`packages/<app>/<app>-<version>-<sha256-prefix>.fre3app` layout; arbitrary URLs,
traversal and encoded path tricks are rejected. Duplicate release identities
are rejected. **Only the two index files are fetched.**

The revision in `verified.json` is the high-water mark: lower revisions fail,
and the same revision requires byte-identical index content. An identical,
correctly signed index is still a successful check. The mark survives restarts,
ordinary app updates and temporary removal of configuration. It is bound to the
repository key, independently of URL. Changing keys or resetting a corrupted
cache requires the operator to deliberately preserve or remove `verified.json`;
there is no automatic reset. Removing that file loses replay history. A frozen,
valid index cannot be identified as stale from schema 1 alone; check timestamps
are local observations, not signed freshness guarantees.

**All outputs and replay state belong to an unprivileged app process.** Other
processes under the shared app UID can alter them. They must never authorize a
privileged installation. Screen must obtain installed metadata from Core; any
later user-requested package download/install must retain Package-Core's own
signature, publisher and release-serial validation. No management group or socket
rights are granted by this app.

## Lifecycle and host checks

`install`, `update` and `restore` check the payload and create the data directory
without fetching anything. `start` starts one background process and returns
without waiting for networking. `status` checks its PID and command line, not
repository availability. `stop` and `uninstall` stop that process with bounded
waiting; repeated actions are safe and configuration/cache are retained.
The client holds an exclusive local lock against simultaneous checks. Network
errors leave the daemon running; no platform timer or restart loop is added.

For a manual check, stop the service and use its installed payload:

```sh
python3 <app-runtime>/payload/client.py --data <app-data-directory> --once
```

This contacts the configured source and needs explicit operator intent.
Offline fixture tests perform no signing, key generation or network access:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/fre3nder-app-update/tests -v
```

Index-flow tests simulate signature responses. OpenSSL verification is tested
separately using a fixed public Ed25519 test vector, including altered bytes and
the wrong public key. No test private keys are stored or used. No package is
signed, built or installed by these tests. Screen UI, installed-version comparison
and explicit package downloads/installation remain follow-up work.
