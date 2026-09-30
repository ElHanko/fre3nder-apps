# Fre3nderScreen display app recipe

`fre3nder/configs/x2000/sources.json` is the sole production source pin.
`fre3nder/scripts/build-x2000-fre3nderscreen` uses that pin in release mode;
`--develop` fetches the current remote `main` and records the resolved commit.
The same cross-build qualifies the binary, themes, and license texts together
and produces the existing RootFS component overlay and the neutral
`local/production/artifacts/x2000/fre3nderscreen/app/` artifact.
The app artifact records its own files and checksums; importing it does not
require the legacy RootFS overlay archive.
Fre3nder owns the Buildroot toolchain, cross-build, and ELF/ABI checks.

`scripts/prepare-fre3nderscreen --artifact <fre3nder-artifact-app-dir>`
imports only release artifacts. Add `--develop` to import only development
artifacts explicitly; there is no automatic mode detection. The flag changes
only the import policy and performs no build. The importer validates the
existing app artifact's mode, source and submodule license provenance, ABI,
file set and checksums. It copies the binary, six themes, eight license texts,
and source artifact manifest unchanged into the ignored
`apps/fre3nderscreen/payload/`, alongside the packaged default config. The
recipe keeps no duplicate license texts; `licenses/UPSTREAM` holds recipe
provenance notes. The importer rejects an existing payload.

After `scripts/prepare-fre3nderscreen --develop --artifact <artifact-app-dir>`
imports a development artifact, a separately authorized development package
build uses:

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

The development cross-build resolves remote `main`; it does not read a local
Fre3nderScreen worktree. Before the first release app build, update the approved
Fre3nder release pin after the source commit is published and qualified. The app
manifest's package version must then match the artifact's source release.

The selected display manager provides API 1 and required framebuffer and
touch paths. The unprivileged service passes these and optional backlight and
beeper paths to Fre3nderScreen. On install, update, or restore it copies the
packaged default config only if no app config exists. App data, logs, and PID
remain in `$FRE3NDER_APP_DATA_DIR`; hardware discovery and permissions remain
in Fre3nder.

Fre3nderScreen is GPL-3.0-only. LVGL, lv_drivers, and spdlog use MIT;
libhv and the inherited wpa_supplicant control client use BSD-3-Clause.
DejaVu and Material Design Icons notices are retained in `payload/licenses/`.
The exact imported commits and artifact checksums travel in the signed
`payload/artifact-manifest.json`.
