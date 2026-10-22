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
or validation failure. Output must be separate from the recipe and supplied build
inputs. The helper does not render manifests, resolve dependencies, build archives
or sign anything.

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

## Selected build inputs

The existing preparers accept optional files in the existing JSON formats:

| Tool | Optional inputs |
| --- | --- |
| Fluidd `prepare-fluidd` | `--upstream FILE`, existing `--archive FILE` |
| Moonraker `fetch-moonraker-inputs` | `--upstream FILE`, `--lock FILE`, existing `--cache DIR` |
| Moonraker `prepare-moonraker` | `--upstream FILE`, `--lock FILE`; existing required `--source DIR`, `--wheels DIR` |
| OctoApp `prepare-octoapp` | `--upstream FILE`, `--lock FILE`, `--requirements FILE`; existing `--source DIR`, `--wheel-dir DIR`, required `--buildroot-output DIR` |
| Doom `build-doom` | `--upstream FILE`; existing `--prepare-only`, `--package-output DIR` |

Absent options retain the maintained recipe inputs and default paths. Selected
input files are read once as bytes, checked as regular files without private-key
material, and never written. `package_stage(..., files=..., overrides=...)`
accepts byte snapshots only for explicitly declared recipe members. Preparers use
the same snapshots for payload preparation and the root `upstream.json`,
`python-wheels.json` and, for OctoApp, `requirements.in`. No alternate recipe or
dependency resolver is introduced. `protected=...` prevents the output directory
from replacing, containing or being inside supplied inputs.

When the selected bytes differ from the maintained inputs, default output moves
to `local/<app>/inputs/<sha256>/package/`. The digest covers destination names and
the full selected input bytes, independently of their host paths. Fluidd download
caches and Moonraker fetch caches use the corresponding `inputs/<sha256>/`
namespace; Doom uses `apps/doom/local/sources/<sha256>/`. Different input sets
therefore retain separate caches and default outputs. Identical inputs reuse
their existing location. Explicit `--output DIR` (Doom: `--package-output DIR`)
still selects a destination to replace after success; use separate destinations
for builds that must coexist. These paths are not a concurrent-build locking
protocol.

For selected inputs, `licenses/UPSTREAM` is prefixed to identify its existing
concrete pin/version notices as the maintained recipe baseline. The selected
root JSON files and generated payload provenance describe the actual build.
License texts, source attachments and integration files remain in the allowlist.
Overrides do not establish redistribution rights: review the selected upstream
and dependency licenses before publication, including changes from the baseline.

Fluidd still consumes an official release ZIP, checks size/hash and the embedded
owner, project and version, and validates the source/license URL identity. It
does not build arbitrary commits with Node. Moonraker consumes a clean checkout
at the selected commit and locked Python 3.12 universal wheels. Moonraker and
OctoApp copy tracked source files only; ignored local files cannot enter the
payload. OctoApp still requires Python 3.12, matching lock/requirements, a source
`[project]` named `OctoApp` at the selected version, a compatible integration
patch, and native bundles passing the existing hash/ABI checks. Alternate native
dependency definitions or bundles are not exposed as overrides. Pillow,
pycryptodome and pycryptodomex cannot be reintroduced through the universal-wheel
lock. A new upstream that needs another patch, dependency target or native ABI
requires recipe work.
The services check the selected signed upstream metadata against the payload
release/runtime metadata instead of fixed Fluidd/OctoApp version constants.

Fre3nderScreen continues to import the platform artifact and its provenance; no
competing Screen pin is added. Package version/serial are separate inputs to
the generic builder; selecting another upstream never changes them automatically.

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

Examples with reviewed external inputs and explicit staging destinations:

```sh
apps/fluidd/scripts/prepare-fluidd --upstream <fluidd-upstream.json> \
  --archive <fluidd-release.zip> --output local/fluidd/selected-package

apps/moonraker/scripts/fetch-moonraker-inputs \
  --upstream <moonraker-upstream.json> --lock <moonraker-wheels.json>
# Use the SOURCE and WHEELS paths printed by the fetcher:
apps/moonraker/scripts/prepare-moonraker \
  --upstream <moonraker-upstream.json> --lock <moonraker-wheels.json> \
  --source <printed-source> --wheels <printed-wheels> \
  --output local/moonraker/selected-package

apps/octoapp/scripts/prepare-octoapp \
  --upstream <octoapp-upstream.json> --lock <octoapp-wheels.json> \
  --requirements <octoapp-requirements.in> --source <clean-checkout> \
  --wheel-dir <locked-wheels> --buildroot-output <buildroot-output> \
  --output local/octoapp/selected-package
```

These preparation commands need no signing key. They do not resolve dependencies
or build native components. After separate signing authorization, use the same
generic builder with the selected package source and reviewed version/serial
pair; see [release metadata](package-layout.md#release-metadata).

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
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests \
  -p test_build_fre3app.py -k Manifest -k Metadata -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_stage_fre3app.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_docker_repository.py -v
for app in fluidd moonraker octoapp doom fre3nderscreen; do
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "apps/$app/tests" -v || exit
done
```

These commands exclude `BuildFre3AppTests`, which generates temporary signing
keys and requires separate authorization. `PackageMetadataTests` simulates the
fingerprint and signature: it checks checksums, metadata, CLI forwarding and a
default archive golden hash from commit `15ef264` without running OpenSSL. It
does not constitute a cryptographic signature verification. App fixtures test
selected input snapshots, rejection of incompatible inputs, cache separation
and preservation of prior staging on failure. Cross-build and wrapper fixtures
stub target builds; no Docker builds or printer actions are performed.

## Coordinated consumers and remaining work

The sibling platform's `scripts/quick-start`, `scripts/build-x2000` and
`scripts/build-x2000-fre3nderscreen-release`, their three Python fixture suites,
and the corresponding documentation use the app-local script paths directly.
Quick Start packages `local/moonraker/package` and `local/fluidd/package`.
There are no old-path forwarding wrappers, symlinks or fallbacks. The Screen
wrappers retain the PASS/Package receipt consumed by the platform.

The optional Docker repository still consumes only already signed archives via
`incoming/`; its image, configuration, keys and index contract are unchanged.

The optional inputs preserve the platform consumers' default invocations; no
platform consumer change is required for these optional CLI additions.

OctoApp's native builder uses the sibling platform's
`scripts/x2000-build-input-sha256 --snapshot DIR` interface for selected tracked
inputs, mounted read-only without Git metadata or production key directories.
The coordinated platform change also removes its complete project mounts;
see the platform's `docs/build.md` for the input selection and mount contract.
Both repositories must contain this interface; there is no whole-project fallback.

Later work must isolate foreign builds from the trusted signing process, keep
dependency/source processing unprivileged, and pass a reviewed immutable staging
artifact to signing. The current shared
native bundle locations and existing native build wrapper are not a sandbox or
independent concurrent native-build environments. Serial allocation and preventing
reuse across builds require a future persistent repository build history. Neither
an upstream override nor the generic builder allocates a serial automatically.
