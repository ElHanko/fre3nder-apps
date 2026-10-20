# Moonraker `.fre3app` migration scaffold

This package is the signed system-app seed after the host and X2000
qualification gates. In particular, the native Python dependencies are still supplied by the
current Buildroot root filesystem. S61 now prepares printer data and delegates service ownership to Package-Core.

## Ownership

* App source pin: `apps/moonraker/upstream.json`
* Universal wheels lock: `apps/moonraker/python-wheels.json`
* Persistent Moonraker configuration / logs / database / G-code:
  `/home/fre3nder/printer_data/` (never deleted by app updates)
* Runtime: Package-Core-selected `apps-v2/moonraker/` directory
* Service startup: platform S61 via Package-Core after Klipper (autostart=false)

## Migration sequence

1. Stage and verify the upstream source and universal dependencies using a
   separate `prepare-moonraker` tool in `fre3nder-apps` (to be implemented).
2. Build a **development-only** signed package using
   `scripts/build-fre3app apps/moonraker --key ... --develop    --version 0.0.0-fre3nder.0.<commit>`. This is not a release.
3. Validate imports, existing configuration, Klipper API socket, readiness,
   upgrade and rollback on the X2000 reference machine.
4. Make the Fre3nder image consume an explicitly signed Moonraker seed from
   `FRE3NDER_SYSTEM_APP_PACKAGES_DIR`, remove legacy RootFS Moonraker payload,
   and retire the conflicting S61 daemon start while retaining config seeding.
5. Confirm SYS reset, HOME preservation, new OTA and OTA rollback end to end.

The image-seed directory is not a repository download endpoint. System-app
updates continue to use package-core release_serial and signatures.
