# Explicit package sources

`apps/<app>/` contains a recipe, its tools and its tests. It is not a package
source directory. Pass only an explicitly prepared package source to
`scripts/build-fre3app`.

## Preparation contract

The Fluidd, Moonraker, OctoApp and Fre3nderScreen preparers now assemble a complete
package source under `local/<app>/package/`. Their `--output DIR` selects another
package source directory, not a payload directory. Preparation does not accept,
read or require a publisher private key. Existing payload preparation functions,
source pins, dependency locks and validation remain in use.

`scripts/stage_fre3app.py` supplies the small shared staging operation: copy the
named recipe files, let the existing app code prepare the payload, validate the
result and replace the destination. The previous destination survives preparation
or validation failure. Output must be separate from the recipe. The helper does
not render manifests, resolve dependencies, build archives or sign anything.

Only `manifest.toml.in`, `service` and the files named by each preparer are copied
from the recipe. In particular, recipe scripts, tests, README files, caches,
unselected license files and local data are not discovered recursively. Prepared
payloads retain their app-specific content, including deliberately bundled upstream
source. Symlinks, non-regular files, Python caches and PEM private-key material in
selected content are rejected. These checks do not replace review of upstream
inputs or their redistribution rights.

Default package sources live under ignored root `local/`. Caches keep their
existing ignored locations, including `apps/doom/local/`. Existing ignored
`apps/<app>/payload/` directories are not used by these build entrypoints.
`apps/dummy/payload/` remains a tracked generic test fixture.

## Package membership before and after

Every archive also contains the rendered `manifest.toml`, `SHA256SUMS` and
`SHA256SUMS.sig`. The template itself is never an archive member. The following
inventory describes the previously bundled recipe files and generated payloads,
before scripts and tests were moved into the recipes.

| App | Previously packaged | Explicit package source now | Purpose |
| --- | --- | --- | --- |
| Dummy | `service`, `payload/message.txt` | Same files, plus the manifest template before packaging | Generic package/lifecycle fixture |
| Fluidd | `service`, `upstream.json`, `licenses/UPSTREAM`, `licenses/LICENSE.fluidd`, `payload/**` | Same files, plus the manifest template | Static web runtime; exact release archive/source identity and GPL notice |
| Moonraker | `service`, `upstream.json`, `python-wheels.json`, `licenses/UPSTREAM`, `README.md`, `.gitignore`, `payload/**` | Everything listed except `README.md` and `.gitignore`, plus the manifest template | Runtime source and Python dependencies; source/wheel locks and payload provenance; upstream license material remains within the payload |
| OctoApp | `service`, `upstream.json`, `python-wheels.json`, `requirements.in`, `native-deps.json`, `patches/0001-fre3nder-disable-system-config.patch`, `licenses/UPSTREAM`, `licenses/LICENSE.octoflatbuffers`, `payload/**` | Same recipe files and runtime payload without Python caches or `Cryptodome/SelfTest/`, plus the manifest template | Patched application, isolated Python dependencies and runtime metadata; integration patch, dependency definitions and license/provenance material |
| Fre3nderScreen | `service`, `licenses/UPSTREAM`, `defaults/fre3nderscreen.json`, `payload/**` | Everything listed except the duplicate root `defaults/fre3nderscreen.json`, plus the manifest template | Binary, themes, seven license texts, `payload/artifact-manifest.json` and the unchanged default configuration at `payload/defaults/fre3nderscreen.json` |
| Doom | Explicit wrapper staging: `service`, `upstream.json`, `licenses/UPSTREAM`, `licenses/LICENSE.doomgeneric`, `payload/bin/doom`, `source/doomgeneric/*`, optionally `payload/iwads/*` | Same files, plus the manifest template | Native engine, upstream license and C/header/Makefile sources including the Fre3nder backend; only explicitly selected private IWADs |

Doom's direct recipe directory was never the wrapper's package input. Its
README and `src/` layout are not the archive layout. The existing source selection
and IWAD allowlist remain authoritative; private IWADs are included only with
`--with-wads` and must not be published.

The inspected OctoApp payload also contained 95 Pillow `.pyc` files and 95
Cryptodome self-test files, including upstream test-key fixtures. The existing
dependency copier now omits `.pyc`, `.pyo` and `__pycache__` instead of carrying
host-generated caches into the package, and omits Cryptodome's optional `SelfTest`
tree. Runtime sources, native libraries and license material stay included; the
dependency-tree hash is computed from the resulting clean tree.

The Moonraker, OctoApp and Fre3nderScreen archive memberships deliberately change. Existing
versions, release serials and pins remain untouched by this refactoring. Do not
publish changed bytes under an already published release identity. A later release
requires separately reviewed version/serial metadata; this change performs no
publication or production signing.

## Commands

For the minimal Dummy fixture:

```sh
python3 scripts/stage_fre3app.py apps/dummy --output local/dummy/package
scripts/build-fre3app local/dummy/package --key <existing-signing-key>
```

Real apps use their existing app-specific preparers:

```sh
apps/fluidd/scripts/prepare-fluidd
scripts/build-fre3app local/fluidd/package --key <existing-signing-key>

apps/moonraker/scripts/prepare-moonraker --source <checkout> --wheels <wheel-cache>
scripts/build-fre3app local/moonraker/package --key <existing-signing-key>

apps/octoapp/scripts/prepare-octoapp --buildroot-output <buildroot-output>
scripts/build-fre3app local/octoapp/package --key <existing-signing-key>

apps/fre3nderscreen/scripts/prepare-fre3nderscreen --artifact <release-artifact>
scripts/build-fre3app local/fre3nderscreen/package --key <existing-signing-key>
```

Doom can stop after its existing cross-build and staging:

```sh
apps/doom/scripts/build-doom --prepare-only --without-wads \
  --buildroot-output <buildroot-output> --package-output local/doom/package
```

This command needs separate cross-build authorization; `--prepare-only` removes
the signing/key requirement, not the cross-build. The normal Doom wrapper still
uses `--output` for the final archive. All normal convenience wrappers call the
same generic package builder with their prepared package source.

## Host regression tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
for app in fluidd moonraker octoapp doom fre3nderscreen; do
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "apps/$app/tests" -v || exit
done
```

Package signature tests use temporary test keys only. Cross-build and wrapper
fixtures stub target builds; these tests do not authorize a production build,
signing operation or printer action.

## Coordinated consumers and remaining work

The sibling platform's `scripts/quick-start`, `scripts/build-x2000` and
`scripts/build-x2000-fre3nderscreen-release`, their three Python fixture suites,
and the corresponding documentation use the app-local script paths directly.
Quick Start packages `local/moonraker/package` and `local/fluidd/package`.
There are no old-path forwarding wrappers, symlinks or fallbacks. The Screen
wrappers retain the PASS/Package receipt consumed by the platform.

The optional Docker repository still consumes only already signed archives via
`incoming/`; its image, configuration, keys and index contract are unchanged.

Later work can add immutable upstream/lock overrides, release metadata overrides,
and automatic serial allocation. Full isolation of foreign builds from publisher
keys, including the existing native Buildroot mounts, remains separate work.
This staging change alone is not a sandbox for upstream code.
