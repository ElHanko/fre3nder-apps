# Doom (Fre3nder X2000 Display Frontend API v1)

DoomGeneric as a native display Fre3app: 320x200 software rendering, rotated
onto the 480x272 X2000 framebuffer, USB keyboard through evdev. No sound, mouse,
or touchscreen gameplay controls.

**This repository distributes only the build recipe and source integration.**
No ready-made Doom `.fre3app` packages or proprietary game data are published.
Each user builds and signs their own package locally.

## Local original game data

For a build with original Doom levels, place your legally obtained WAD files
under the ignored working directory:

```text
apps/doom/local/iwads/DOOM.WAD
apps/doom/local/iwads/DOOM2.WAD
apps/doom/local/iwads/TNT.WAD
apps/doom/local/iwads/PLUTONIA.WAD
```

The builder accepts any nonempty subset of those four filenames, requires a
regular (non-symlink) file with an `IWAD` header for each, and never includes
anything else from `apps/doom/local/`. `.gitignore` must include
`/apps/doom/local/`.

## Local build: choose whether to include WADs

Requires a prepared Fre3nder X2000 Buildroot toolchain, `git`, `make`,
`python3`, `openssl`, and an **existing** Ed25519 app signing key. No keys are
generated. The pinned DoomGeneric checkout is cached in the ignored
`apps/doom/local/upstream/` directory.

**Personal development build, including any available original IWADs:**

```sh
apps/doom/scripts/build-doom --develop --with-wads
```

This includes those WADs **inside the signed `.fre3app`**, at
`payload/iwads/`. The result is for the owner's own use, **not for public
redistribution**.

**Development build without game data:**

```sh
apps/doom/scripts/build-doom --develop --without-wads
```

This builds the engine only. The owner must supply their own IWAD files on the
printer under `/home/fre3nder/.local/share/doom/iwads/` before starting Doom.
The same runtime directory also works as a user override for a bundled WAD.

Both variants are written locally to `dist/`, with a `with-wads` or
`without-wads` suffix to distinguish their filenames. No upload or publication
happens. The bundled source files and GPL license are included for compliance.

Development packages have `release_serial = 0`; the default version is
`0.1.0-fre3nder.0.1`. When updating an already installed development package,
choose a **new** version even if you only change which WADs were packaged:

```sh
apps/doom/scripts/build-doom --develop --with-wads --version 0.1.0-fre3nder.0.2
```

Other options: `--buildroot-output PATH`, `--key PATH`, `--output PATH`. The
recipe also supports locally building a non-development package by omitting
`--develop`; this does not authorize or trigger public release of an artifact.

`--prepare-only` runs the same cross-build and explicit source staging without
reading a signing key or signing. The package source defaults to ignored
`local/doom/package/`; `--package-output DIR` overrides it. The normal wrapper
passes that source to the unchanged generic builder. Cross-build authorization
is still required. See [the staging contract](../../docs/package-staging.md).

`--upstream FILE` selects another DoomGeneric commit using the existing upstream
JSON fields. Repository identity, GPL license, source layout, backend inventory
and target binary checks remain required. The selected file is read without
modification and included in staging alongside the GPL source attachment. Changed
inputs use `apps/doom/local/sources/<sha256>/`; package output defaults to
`local/doom/inputs/<sha256>/package/`. `--package-output` selects another package
destination without changing that source cache.

Changed upstream inputs cannot be signed directly as stable packages by this
wrapper. Use `--prepare-only` and then the generic
builder's `--version VERSION --release-serial N` after the corresponding build
and signing authorizations, choosing a new stable identity. Development signing
with changed inputs requires an explicit, unused `--version` different from the
default `0.1.0-fre3nder.0.1`. Unchanged inputs retain the existing defaults.
The wrapper keeps its development-only `--version` semantics and allocates no
new identity automatically.

## Runtime and game selection

Doom uses the first available source for the selected filename:

1. An explicitly provided, regular IWAD in the persistent app-data `iwads/`
   directory (user override).
2. A signed IWAD bundled into `payload/iwads/`, if the build included it.

By default, Doom selects `DOOM.WAD`. To select Doom II or another installed
IWAD, put its exact filename in the persistent file
`/home/fre3nder/.local/share/doom/selected-iwad`:

```text
DOOM2.WAD
```

Supported names: `DOOM.WAD`, `DOOM2.WAD`, `TNT.WAD`, `PLUTONIA.WAD`.
Select the game while the application is stopped. WADs, configuration and saves
under app data survive package updates and uninstall.

## Installation and selection

Use the existing Fre3nder CLI:

```sh
fre3nder app verify /path/to/doom.fre3app
fre3nder app install /path/to/doom.fre3app
fre3nder app display select doom
```

Selecting Doom replaces Fre3nderScreen on tty7; both do not run concurrently.
A restart of the selected display service may be required according to the
platform CLI/runtime procedure. Keyboard: arrow keys, Ctrl (fire), Space (use),
Shift (run), Esc (menu). Ctrl+Alt+F1/F7 switches between tty1 and tty7.

The Display Frontend API v1 supplies framebuffer, VT and touch but no separate
USB keyboard path. The app discovers Linux evdev keyboards and requires
appropriate permissions on their `event*` nodes via the existing `input` group.
This assumption has not been qualified on X2000 hardware. No root service,
platform policy, or RootFS change is introduced by this recipe.

## Licensing

The DoomGeneric engine and integration backend are GPL-2.0-or-later; see
`licenses/UPSTREAM` and the upstream LICENSE included when building.
Proprietary WADs remain subject to their own license. Do not commit them, push
them, or publish an artifact that bundles them without redistribution rights.
