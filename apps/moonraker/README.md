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
apps/moonraker/scripts/prepare-moonraker --source <moonraker-checkout> --wheels <wheel-cache>
```

For a fresh clone, the optional input fetcher fills the ignored local cache
from the pinned Moonraker Git commit and the SHA-256-locked PyPI wheels:

```sh
apps/moonraker/scripts/fetch-moonraker-inputs
apps/moonraker/scripts/prepare-moonraker \
  --source local/moonraker/source \
  --wheels local/moonraker/wheels
```

The fetcher reuses matching cached inputs, rejects modifications, and does not
prepare payloads or sign packages. The offline `prepare-moonraker` workflow above
remains available when the source checkout and wheels are supplied separately.

Both commands also accept `--upstream FILE --lock FILE`. Supply the same reviewed
JSON inputs to the fetcher and preparer. The source commit and wheel lock are
independent; neither command resolves or upgrades dependencies. With changed
input bytes, the fetcher prints `SOURCE` and `WHEELS` under
`local/moonraker/inputs/<sha256>/`; use those printed paths rather than the default
paths above. The preparer's default output becomes the corresponding
`inputs/<sha256>/package/`, or select `--output DIR` explicitly. The actual selected
JSON bytes and generated source/wheel provenance are included in staging.

The preparer works offline, verifies the source commit and wheel hashes, and
stages `local/moonraker/package/` with the manifest template, service, selected
provenance/license files and a payload containing source and Python modules.
`--output DIR` selects the complete package source directory.
It copies tracked source files, excluding Git metadata, ignored local files and
Python caches. Repeated runs replace the existing
package source only after successful staging; failures preserve the previous
source. Bundled source and wheels retain their upstream license texts.

## Packaging and image integration

Use `scripts/build-fre3app local/moonraker/package --key <official-app-key>` for a
release recipe with a positive, increasing `release_serial`. For a development
snapshot, use `--develop --version <unique-development-version>`; its serial
is zero. The checked-in template has release serial `1`.
For explicitly selected stable metadata, pass both `--version VERSION` and
`--release-serial N` to that same builder, choosing an unused release identity.
The maintained template and pins remain unchanged; no serial is assigned for you.
Building or signing requires explicit operator
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
