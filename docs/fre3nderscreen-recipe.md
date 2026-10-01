# Fre3nderScreen display app recipe

`fre3nder/configs/x2000/sources.json` is the sole production source pin.
`fre3nder/scripts/build-x2000-fre3nderscreen` uses that pin in release mode;
`--develop` fetches the current remote `main` and records the resolved commit.
The same cross-build qualifies the binary, themes, and license texts together
and produces the neutral `local/production/artifacts/x2000/fre3nderscreen/app/`
artifact. The app artifact
records its own files and checksums; no Fre3nderScreen RootFS component overlay
is produced.
Fre3nder owns the Buildroot toolchain, cross-build, and ELF/ABI checks.

The prepared release source is `2026.2` at
`63e7ecb9fff980b53f4987ef9994675aecf9e0a2`. The release template specifies
`2026.2-fre3nder.2`, with `release_serial = 2`, continuing the increasing
package release sequence. No tag, release binary, or signed release package
has been produced for this preparation.

The normal release package command is:

```sh
scripts/build-fre3nderscreen-release \
  --artifact <fre3nder-app-artifact-dir> --key <private-ed25519-key>
```

The wrapper requires both paths and accepts only release artifacts. It removes
only the generated `apps/fre3nderscreen/payload/`, rejecting symlinked directory
boundaries and unexpected payload files. It then calls `prepare-fre3nderscreen`
without `--develop` and `build-fre3app` with the supplied key. Import or package
errors stop the wrapper. On success it reports the builder's package path and
SHA-256 in a PASS block. It does not cross-build, copy a factory seed, or deploy.

The underlying `scripts/prepare-fre3nderscreen --artifact <fre3nder-artifact-app-dir>`
imports only release artifacts. Add `--develop` to import only development
artifacts explicitly; there is no automatic mode detection. The flag changes
only the import policy and performs no build. The importer validates the
existing app artifact's mode, source and submodule license provenance, ABI,
file set and checksums. It copies the binary, six themes, eight license texts,
and source artifact manifest unchanged into the ignored
`apps/fre3nderscreen/payload/`, alongside the packaged default config. The
recipe keeps no duplicate license texts; `licenses/UPSTREAM` holds recipe
provenance notes. The importer rejects an existing payload.

Both the cross-builder and importer retain `YEAR.SERIES` for development:
`2026.1.1` becomes `2026.1.<source-commit>`, and `2026.2` becomes
`2026.2.<source-commit>`, using the first seven commit characters.

For the historical `2026.1` development example below, after
`scripts/prepare-fre3nderscreen --develop --artifact <artifact-app-dir>`
imports a matching development artifact, a separately authorized package build
uses:

```sh
scripts/build-fre3app apps/fre3nderscreen --key <signing-key> \
  --develop --version 2026.1.14cd415-fre3nder.0.<recipe-commit>
```

The supplied version identifies both
the Fre3nderScreen source commit (`14cd415`) and the fre3nder-apps recipe
commit (`<recipe-commit>`), meaning the committed recipe state used to build
the package. Development packages use `release_serial = 0`, the same
publisher and signing key as releases, and are not intended for publication.
The generic builder does not resolve commits or read the artifact manifest;
the caller supplies the version. `manifest.toml.in` remains the release
template, with its version and serial unchanged on disk.

The development package `2026.1.14cd415-fre3nder.0.4796448` (`release_serial = 0`),
built from Fre3nderScreen source `14cd41599f1ee8dec659b282e54762fd61552c5a`
and fre3nder-apps commit `4796448`, was installed and selected through the
Fre3nder factory-app path on the reference printer. Its display, touch,
calibration, Moonraker connection, and beeper passed hardware validation. The
prepared `2026.2` source retains that application code, patches, and submodules;
only `README.md` and `DEVELOPMENT.md` changed after `14cd415`. This historical
qualification does not establish hardware qualification of the unbuilt
`2026.2` release binary or package.

The signed package is supplied to the Fre3nder RootFS build as a factory seed.
On a fresh persistent system, Fre3nder installs it through the package core
and explicitly selects it as the display frontend.

The development cross-build resolves remote `main`; it does not read a local
Fre3nderScreen worktree. A release app build must import an artifact built from
the approved Fre3nder release pin. The app manifest's package version must
match the artifact's source release.

The selected display manager provides API 1 and required framebuffer and
touch paths. The unprivileged service passes these and optional backlight and
beeper paths to Fre3nderScreen. On first setup it copies a regular, non-symlink
legacy config from
`/home/fre3nder/.fre3nder/fre3nderscreen/fre3nderscreen.json` if present;
otherwise it copies the packaged default. An existing app config always wins,
and the legacy file remains available for rollback. App data, logs, and PID
remain in `$FRE3NDER_APP_DATA_DIR`; hardware discovery and permissions remain
in Fre3nder.

Fre3nderScreen is GPL-3.0-only. LVGL, lv_drivers, and spdlog use MIT;
libhv and the inherited wpa_supplicant control client use BSD-3-Clause.
DejaVu and Material Design Icons notices are retained in `payload/licenses/`.
The exact imported commits and artifact checksums travel in the signed
`payload/artifact-manifest.json`.
