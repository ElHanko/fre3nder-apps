# Fre3nderScreen display app recipe

Fre3nderScreen owns the UI application and SDL simulator. Fre3nder owns the
Buildroot toolchain, platform integration and X2000 cross-build. This repository
imports the neutral app artifact and packages/signs the `.fre3app`.

## Source and artifact contract

`fre3nder/configs/x2000/sources.json` is the sole production source pin.
The pin selects `c70c616`, using LVGL 9.6.0, libhv 1.3.4 with embedded
nlohmann/json 3.12.0, and spdlog 1.17.0 with bundled fmt 12.1.0. LVGL's
integrated fbdev/evdev/SDL drivers replace the separate `lv_drivers` submodule.
`fre3nder/scripts/build-x2000-fre3nderscreen` fetches the pinned commit in release
mode, verifies the three submodule pins, applies the single opt-in evdev
raw-mode patch, and checks the statically linked MIPS32r2 hardfloat ELF/ABI.
It produces `local/production/artifacts/x2000/fre3nderscreen/app/`, with:

- `bin/fre3nderscreen` and six themes (blue, green, pink, purple, red, yellow);
- six license files: `COPYING`, `LVGL-LICENSE`,
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
`local/fre3nderscreen/package/payload/`, adding the packaged default config.
The complete package source also contains the unchanged manifest template,
service and `licenses/UPSTREAM`. `--output DIR` selects that package source;
an existing source is replaced only after successful preparation and validation.
There is no automatic release/development mode
selection and no fallback to an old file set.

## Release package

The release template is `2026.3-fre3nder.1` with `release_serial = 3`. Release
serials must be positive and increase for subsequent releases. Development packages
use serial `0`; Core requires explicit `--allow-downgrade` to replace an installed release
with one of them. Packaging does not install or downgrade any app.

After explicit build/signing approval, from this repository:

```sh
apps/fre3nderscreen/scripts/build-fre3nderscreen-release \
  --artifact <fre3nder-app-artifact-dir> --key <private-ed25519-key>
```

The wrapper accepts release artifacts only. It replaces the generated
package source, rejecting symlinked recipe boundaries and a non-directory source,
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
apps/fre3nderscreen/scripts/build-fre3nderscreen-development \
  --artifact <development-artifact-app-dir> --key <private-ed25519-key>
```

It uses `prepare-fre3nderscreen --develop` and
`build-fre3app --develop --version ...`, producing
`<artifact.source.release>-fre3nder.0.<apps-commit>`, serial `0`.
`artifact.source.release` is `YEAR.SERIES.<screen-commit>` (seven commit
characters). The Screen checkout supplies the development series, independently
of the release package template. For example, `2026.4.a` yields
`2026.4.<screen-commit>`.
The wrapper allows tracked recipe changes but reports `Recipe worktree: dirty`.
Commit-based version strings do not identify pending changes; inspect the source
worktree hash and package checksum as well. This path does not copy a Factory
seed or deploy, and never imports a release artifact as development or vice versa.

For non-signing import validation, `apps/fre3nderscreen/scripts/prepare-fre3nderscreen --develop
--artifact <artifact-app-dir> --output <unused-temporary-directory>` validates
and prepares a package source from an existing Development artifact only; it
performs no build or signing. The [staging inventory](package-staging.md) records
the deliberate removal of the duplicate root default config. Versions and
serials remain unchanged; do not republish changed package bytes with an
existing release identity.

## Verify a release package

Verify the signed package with Fre3nder Package-Core and the official public
key. Check the version, release serial, display API and the source commit,
submodules and ABI in the signed `payload/artifact-manifest.json`. Verify
that the Factory seed matches the package byte for byte. Keep the published
source tag and package checksum together. See the platform's
[display qualification](https://github.com/ElHanko/fre3nder/blob/main/docs/display.md#configuration-and-qualification-boundary)
for the tested reference configurations.

## Runtime and provenance

Fre3nder ships the signed Factory app in the RootFS and automatically
installs/selects it on first installation, in persistent SYS by default. A
firmware deployment does not automatically replace an installed Screen version;
after SYS reset, signed-cache recovery restores that version from HOME.
To explicitly apply the embedded Factory app through Core:

```sh
fre3nder app update /usr/share/fre3nder/factory-apps/fre3nderscreen.fre3app
```

Follow Fre3nder's [verification and update procedure](https://github.com/ElHanko/fre3nder/blob/main/docs/installation.md#update-the-installed-display-app).
This differs from required system apps, which automatically reconcile newer
image seeds at boot by increasing release serial. The display manager
provides API 1, VT, framebuffer and touch paths; the unprivileged package service
passes them and optional backlight/beeper paths to Screen. App data, logs and PID
remain in `$FRE3NDER_APP_DATA_DIR`. An existing app config wins; first setup can
copy a regular non-symlink legacy config from
`/home/fre3nder/.fre3nder/fre3nderscreen/fre3nderscreen.json` or use the packaged
defaults. Device discovery, permissions and privileged management belong to Core.

Fre3nderScreen retains its Guppy Screen history and GPL-3.0-only provenance.
LVGL and spdlog use MIT; libhv uses BSD-3-Clause. `LVGL-LICENSE` also contains
the Zlib notice of LVGL's bundled LodePNG decoder. DejaVu and Material
Design Icons notices remain in `payload/licenses/`. Exact imported source,
submodule commits and artifact checksums travel in the signed
`payload/artifact-manifest.json`. See `apps/fre3nderscreen/licenses/UPSTREAM`.
