# Fre3nderScreen display app recipe

Fre3nderScreen owns the UI application and SDL simulator. Fre3nder owns the
Buildroot toolchain, platform integration and X2000 cross-build. This repository
imports the neutral app artifact and packages/signs the `.fre3app`.

## Source and artifact contract

`fre3nder/configs/x2000/sources.json` is the sole production source pin.
`fre3nder/scripts/build-x2000-fre3nderscreen` fetches that exact commit in release
mode, verifies the submodule pins, applies the three Screen-owned dependency
patches, and checks the statically linked MIPS32r2 hardfloat ELF/ABI.
It produces `local/production/artifacts/x2000/fre3nderscreen/app/`, with:

- `bin/fre3nderscreen` and six themes (blue, green, pink, purple, red, yellow);
- seven license texts: `COPYING`, `LVGL-LICENSE`, `LV-DRIVERS-LICENSE`,
  `LIBHV-LICENSE`, `SPDLOG-LICENSE`, `DEJAVU-FONTS-LICENSE`,
  `MATERIAL-DESIGN-ICONS-LICENSE`;
- `artifact-manifest.json` with source/submodule/build provenance and file hashes;
- `SHA256SUMS` covering all artifact files including that manifest.

The cleaned Screen source no longer contains the inherited WPA control code.
`WPA-SUPPLICANT-LICENSE` is outside the new app contract. Fre3nder's independent
Buildroot `wpa_supplicant` service remains part of Core. Old artifacts and
existing generated payloads retain their original notices; rebuild/re-import
for the new contract rather than editing old artifact manifests or checksums.

The importer validates the exact file set, mode, source release, ABI, submodule
provenance, manifest hashes and `SHA256SUMS`. Unexpected files, symlinks and
unsupported members remain errors. It copies the verified binary, themes,
license bytes and artifact manifest unchanged into ignored
`apps/fre3nderscreen/payload/`, adding the packaged default config. It rejects
an existing output directory. There is no automatic release/development mode
selection and no fallback to an old file set.

## Release package

The template remains `2026.2-fre3nder.2`, `release_serial = 2`. Release serials
must be positive and increase for subsequent releases. No version or serial
change is needed for this pre-release cleanup. Development packages use serial
`0`; Core requires explicit `--allow-downgrade` to replace an installed release
with one of them. Packaging does not install or downgrade any app.

After explicit build/signing approval, from this repository:

```sh
scripts/build-fre3nderscreen-release \
  --artifact <fre3nder-app-artifact-dir> --key <private-ed25519-key>
```

The wrapper accepts release artifacts only. It replaces only the generated
payload, rejecting symlinked recipe boundaries and a non-directory payload,
then calls `prepare-fre3nderscreen` and `build-fre3app`. Errors stop the wrapper;
success reports the package path and SHA-256. It performs no cross-build,
Factory-seed copy or deployment. Use an existing key; do not generate one for
this integration.

For the combined cross-build, signing and local Factory-seed preparation,
run the existing wrapper from Fre3nder after its separate build/signing approval:

```sh
scripts/build-x2000-fre3nderscreen-release \
  --apps-repo <fre3nder-apps-root> --key <private-ed25519-key>
```

This requires the prepared Fre3nder Buildroot host toolchain, fetchable pinned
Screen source and a clean tracked fre3nder-apps worktree, staged and unstaged.
It runs the cross-builder and this repository's release wrapper, then copies
the identical package atomically to Fre3nder's
`local/production/factory-apps/fre3nderscreen.fre3app`. It does not build a RootFS
or deploy. The standalone apps wrapper does not itself enforce a clean worktree;
do not use it to bypass the combined release workflow's check. The Fre3nder
worktree status and build-input hash are recorded in the artifact; use reviewed,
committed inputs for a reproducible release.

## Development snapshots

The cross-builder's `--develop` uses remote `main`, recording the resolved
commit. For a local worktree, explicitly set
`FRE3NDER_FRE3NDERSCREEN_SOURCE=../fre3nderscreen` in Fre3nder and use
`scripts/build-x2000-fre3nderscreen --develop`. The read-only checkout is copied
into isolated build work, including pending edits/new files/deletions and clean
initialized submodules. The source records baseline commit, local origin,
worktree status and content hash. Without that variable, pending changes in the
conventional sibling Screen checkout block the remote-main development path.
Release mode never substitutes a local worktree or `main` for the pin.

The separately authorized development package command is:

```sh
scripts/build-fre3nderscreen-development \
  --artifact <development-artifact-app-dir> --key <private-ed25519-key>
```

It uses `prepare-fre3nderscreen --develop` and
`build-fre3app --develop --version ...`, producing
`<artifact.source.release>-fre3nder.0.<apps-commit>`, serial `0`.
`artifact.source.release` is `YEAR.SERIES.<screen-commit>` (seven commit
characters); for example, `2026.2.<screen-commit>`. The template stays unchanged.
The wrapper allows tracked recipe changes but reports `Recipe worktree: dirty`.
Commit-based version strings do not identify pending changes; inspect the source
worktree hash and package checksum as well. This path does not copy a Factory
seed or deploy, and never imports a release artifact as development or vice versa.

For non-signing import validation, `scripts/prepare-fre3nderscreen --develop
--artifact <artifact-app-dir> --output <unused-temporary-directory>` validates
and copies an existing Development artifact only; it performs no build.

## Remaining 2026.2 release steps

The current Fre3nder source pin remains
`63e7ecb9fff980b53f4987ef9994675aecf9e0a2`; it predates native management and
cleanup. The final commit does not yet exist. Separately approve/commit the
cleanup, make it fetchable, and explicitly update the Fre3nder pin, its matching
test assertion and provenance documentation before the release build. Commit the
matching apps integration when authorized so the combined wrapper's clean-tree
check passes. Do not bypass that check or invent a replacement commit hash.

The existing local and remote Screen tag `2026.2` also points to `63e7ecb`.
It must remain untouched until a separate decision authorizes correcting it;
choosing a new version instead requires consistent source/package version changes.
Build the pinned app, sign/package it, verify the Factory seed, then separately
authorize on-device installation and regression testing. Publication requires
separate tag/push/release approval.

The operator reports X2000 hardware tests with Fre3nder 2026.5 and Screen
`65b37b9`: unprivileged `fre3nder` startup with primary GID
`fre3nder-management`, protected root-owned runtime, native System and Apps
(including writes), and complete OTA through backup, readback, activation and
restart. The subsequent cleanup passed Docker/SDL build and manual UI testing
according to the operator. Neither result qualifies the future release binary
or every UI function. Earlier Factory-app tests remain historical evidence.

## Runtime and provenance

Fre3nder installs/selects the signed Factory seed on a fresh persistent system;
it does not automatically replace an already installed app. The display manager
provides API 1, VT, framebuffer and touch paths; the unprivileged package service
passes them and optional backlight/beeper paths to Screen. App data, logs and PID
remain in `$FRE3NDER_APP_DATA_DIR`. An existing app config wins; first setup can
copy a regular non-symlink legacy config from
`/home/fre3nder/.fre3nder/fre3nderscreen/fre3nderscreen.json` or use the packaged
defaults. Device discovery, permissions and privileged management belong to Core.

Fre3nderScreen retains its Guppy Screen history and GPL-3.0-only provenance.
LVGL, lv_drivers and spdlog use MIT; libhv uses BSD-3-Clause. DejaVu and Material
Design Icons notices remain in `payload/licenses/`. Exact imported source,
submodule commits and artifact checksums travel in the signed
`payload/artifact-manifest.json`. See `apps/fre3nderscreen/licenses/UPSTREAM`.
