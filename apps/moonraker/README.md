# Moonraker system `.fre3app`

Moonraker runs as an official signed system app on Fre3nder. Its source pin,
universal wheels, packaging and unprivileged service belong to this repository.
The X2000 reference system has run this package with Klipper and Moonraker
reporting `active` and Package-Core confirming the running official system app.
Native Python dependencies and libraries remain supplied by the Buildroot
platform.

## Preparing the payload

`apps/moonraker/upstream.json` pins the upstream source and license;
`apps/moonraker/python-wheels.json` records exact wheel versions, filenames,
SHA256 hashes, upstream URLs and licenses. Supply a clean Git checkout at that
source commit and a directory containing the locked wheels:

```sh
scripts/prepare-moonraker --source <moonraker-checkout> --wheels <wheel-cache>
```

For a fresh clone, the optional input fetcher fills the ignored local cache
from the pinned Moonraker Git commit and the SHA-256-locked PyPI wheels:

```sh
scripts/fetch-moonraker-inputs
scripts/prepare-moonraker \
  --source local/moonraker/source \
  --wheels local/moonraker/wheels
```

The fetcher reuses matching cached inputs, rejects modifications, and does not
prepare payloads or sign packages. The offline `prepare-moonraker` workflow above
remains available when the source checkout and wheels are supplied separately.

The preparer works offline, verifies the source commit and wheel hashes, and
stages `apps/moonraker/payload/` with source, Python modules and provenance.
It excludes Git metadata and Python caches. Repeated runs replace the existing
payload only after successful staging; failures preserve the previous payload. Bundled source and wheels retain their upstream license texts.

## Packaging and image integration

Use `scripts/build-fre3app apps/moonraker --key <official-app-key>` for a
release recipe with a positive, increasing `release_serial`. For a development
snapshot, use `--develop --version <unique-development-version>`; its serial
is zero. The checked-in bootstrap template is a development recipe until
release metadata is assigned. Building or signing requires explicit operator
authorization.

Supply the resulting official signed package as `moonraker.fre3app` in the
platform's `FRE3NDER_SYSTEM_APP_PACKAGES_DIR`. A release image requires
`release_serial >= 1`; a development image also accepts serial zero. The
platform verifies the package, embeds it in the image, and reconciles it at boot.
This directory is an image input, not a package download endpoint.

## Runtime ownership

Package-Core installs and selects the `apps-v2/moonraker/` runtime and invokes
its service as the unprivileged `fre3nder` user. Platform S61 prepares the
configuration and runtime directory, checks Klipper, and starts Moonraker via
Package-Core after S58 app recovery and S59/S60 Klipper startup.
`autostart = false` keeps S65 from starting it independently.

The app service owns its PID, start/stop/status and API-socket readiness.
Package-Core restarts an already running service after a manual app update and
restores the previous runtime on failure. Configuration, logs, database and
G-code remain in `/home/fre3nder/printer_data/`; package updates do not delete
that state. There is no on-device pip or Git updater for this signed runtime.
