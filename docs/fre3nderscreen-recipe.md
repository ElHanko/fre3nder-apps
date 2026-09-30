# Fre3nderScreen display app recipe

`fre3nder/configs/x2000/sources.json` is the sole production source pin.
`fre3nder/scripts/build-x2000-fre3nderscreen` uses that pin in release mode;
`--develop` fetches the current remote `main` and records the resolved commit.
The same cross-build produces the existing RootFS component overlay and the
neutral `local/production/artifacts/x2000/fre3nderscreen/app/` artifact.
The app artifact records its own files and checksums; importing it does not
require the legacy RootFS overlay archive.
Fre3nder owns the Buildroot toolchain, cross-build, and ELF/ABI checks.

`scripts/prepare-fre3nderscreen --artifact <fre3nder-artifact-app-dir>`
validates the existing app artifact's mode, provenance, ABI, file set and
checksums. It copies the binary, six themes, source artifact manifest, and
packaged default config into the ignored `apps/fre3nderscreen/payload/`.
The eight source license texts in `apps/fre3nderscreen/licenses/` are compared
with the artifact's licenses before import and are included at the signed
package's `licenses/` root. The importer rejects an existing payload.

Only release artifacts are importable. Development artifacts remain useful for
Fre3nder component tests, but there is no development `.fre3app` packaging
policy yet. In particular, a development artifact must not be paired with the
release `manifest.toml.in` or its `release_serial = 1`. The generic
`scripts/build-fre3app` is a separate, signing package step; no package has
been built or signed for this recipe.

The current release pin predates Phase 3a's framebuffer runtime change.
Those uncommitted source changes remain in `fre3nderscreen`. A future
`--develop` cross-build can include them only after a real commit is
available on the remote `main`; it intentionally does not read a local
worktree. Before the first release app build, update the approved Fre3nder
release pin after the source commit is published and qualified. The app
manifest's package version must then match the artifact's source release.

The selected display manager provides API 1 and required framebuffer and
touch paths. The unprivileged service passes these and optional backlight and
beeper paths to Fre3nderScreen. On install, update, or restore it copies the
packaged default config only if no app config exists. App data, logs, and PID
remain in `$FRE3NDER_APP_DATA_DIR`; hardware discovery and permissions remain
in Fre3nder.

Fre3nderScreen is GPL-3.0-only. LVGL, lv_drivers, and spdlog use MIT;
libhv and the inherited wpa_supplicant control client use BSD-3-Clause.
DejaVu and Material Design Icons notices are retained in `licenses/`.
The exact imported commits and artifact checksums travel in the signed
`payload/artifact-manifest.json`.
