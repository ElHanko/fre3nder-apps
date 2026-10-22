#!/usr/bin/env python3
"""Publish explicitly permitted, already-signed Fre3nder packages.

This first stage intentionally does NOT build, re-sign, mirror, or install apps.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import tomllib
import zipfile

MAX_PACKAGE = 256 * 1024 * 1024
MAX_FILES = 4096
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]*\Z")
HASH_LINE = re.compile(r"([0-9a-f]{64})  (.+)\n\Z")
REQUIRED = {"manifest.toml", "service", "SHA256SUMS", "SHA256SUMS.sig"}
STOP = threading.Event()


class RepositoryError(Exception):
    pass


def fail(message):
    raise RepositoryError(message)


def run_openssl(*args, data=None):
    result = subprocess.run(
        ["openssl", *map(str, args)], input=data, capture_output=True,
        check=False,
    )
    if result.returncode:
        fail("OpenSSL operation failed: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


def public_fingerprint(path, private=False):
    options = ("pkey", "-in", path, "-pubout", "-outform", "DER") if private else (
        "pkey", "-pubin", "-in", path, "-outform", "DER")
    der = run_openssl(*options)
    # SubjectPublicKeyInfo DER encoding of an Ed25519 public key.
    if len(der) != 44 or not der.startswith(bytes.fromhex("302a300506032b6570032100")):
        fail("signing key is not Ed25519")
    return hashlib.sha256(der).hexdigest()


def verify_signature(public_key, content, signature):
    if len(signature) != 64:
        fail("invalid Ed25519 signature length")
    with tempfile.TemporaryDirectory(prefix="fre3nder-repo-verify-") as temp:
        data_file = Path(temp) / "message"
        sig_file = Path(temp) / "signature"
        data_file.write_bytes(content)
        sig_file.write_bytes(signature)
        run_openssl("pkeyutl", "-verify", "-rawin", "-pubin",
                    "-inkey", public_key, "-in", data_file, "-sigfile", sig_file)


def sign_index(private_key, content):
    with tempfile.TemporaryDirectory(prefix="fre3nder-repo-sign-") as temp:
        input_file = Path(temp) / "index"
        signature_file = Path(temp) / "index.sig"
        input_file.write_bytes(content)
        run_openssl("pkeyutl", "-sign", "-rawin", "-inkey", private_key,
                    "-in", input_file, "-out", signature_file)
        signature = signature_file.read_bytes()
        if len(signature) != 64:
            fail("invalid repository Ed25519 signature length")
        return signature


def is_safe_member(name):
    parts = name.split("/")
    return bool(name) and not name.startswith("/") and "\\" not in name and all(
        part not in ("", ".", "..") and all(32 <= ord(c) < 127 for c in part)
        for part in parts
    )


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(path, app_config, publisher_key, publisher_fingerprint):
    """Inspect and authenticate a package; do not extract it."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PACKAGE:
        fail(f"unsafe or oversized package: {path}")
    if path.stat().st_size == 0:
        fail(f"empty package: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            if len(names) > MAX_FILES or len(set(names)) != len(names):
                fail("duplicate members or too many package files")
            if not REQUIRED.issubset(names):
                fail("package is missing required signed members")
            if sum(entry.file_size for entry in infos) > MAX_PACKAGE:
                fail("oversized uncompressed package")
            for entry in infos:
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if (not is_safe_member(entry.filename) or entry.is_dir()
                        or entry.flag_bits & 1 or kind not in (0, stat.S_IFREG)):
                    fail(f"unsafe package member: {entry.filename}")
            if archive.getinfo("manifest.toml").file_size > 1024 * 1024:
                fail("oversized manifest")
            if archive.getinfo("SHA256SUMS").file_size > 1024 * 1024:
                fail("oversized SHA256SUMS")
            manifest = tomllib.loads(archive.read("manifest.toml").decode("utf-8"))
            sums = archive.read("SHA256SUMS")
            sig = archive.read("SHA256SUMS.sig")
            entries = []
            for line in sums.decode("ascii").splitlines(keepends=True):
                matched = HASH_LINE.fullmatch(line)
                if not matched:
                    fail("malformed SHA256SUMS")
                entries.append((matched.group(2), matched.group(1)))
            expected = sorted(set(names) - {"SHA256SUMS", "SHA256SUMS.sig"})
            if [name for name, _ in entries] != expected:
                fail("SHA256SUMS does not exactly enumerate signed files")
            for name, expected_digest in entries:
                digest = hashlib.sha256()
                with archive.open(name) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected_digest:
                    fail(f"package checksum mismatch: {name}")
            verify_signature(publisher_key, sums, sig)
    except (zipfile.BadZipFile, UnicodeError, tomllib.TOMLDecodeError, KeyError) as error:
        fail(f"invalid package {path.name}: {error}")
    app = manifest.get("app", {})
    publisher = manifest.get("publisher", {})
    target = manifest.get("target", {})
    name = app.get("name")
    version = app.get("version")
    serial = app.get("release_serial")
    if (not isinstance(name, str) or not NAME.fullmatch(name)
            or name != app_config["name"]):
        fail(f"package app does not match configured name: {path.name}")
    if (not isinstance(version, str) or len(version) > 128
            or not VERSION.fullmatch(version)):
        fail("invalid version string")
    if type(serial) is not int or serial < 0:
        fail("invalid release serial")
    if serial == 0 and app_config["channel"] != "testing":
        fail("development packages are only allowed in testing channel")
    if publisher.get("id") != app_config["publisher"] or publisher.get(
            "key_fingerprint") != publisher_fingerprint:
        fail("app publisher identity or key fingerprint mismatch")
    if target != {"platform": "fre3nder-x2000", "arch": "mipsel"}:
        fail("unsupported Fre3nder target")
    if manifest.get("format") != 1:
        fail("unsupported package format")
    return {
        "name": name,
        "version": version,
        "release_serial": serial,
        "publisher": {"id": app_config["publisher"],
                      "key_fingerprint": publisher_fingerprint},
        "target": target,
        "channel": app_config["channel"],
        "size": path.stat().st_size,
        "sha256": hash_file(path),
    }


def load_config(path):
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    repo = config.get("repository", {})
    name = repo.get("name")
    key = repo.get("signing_key")
    if not isinstance(name, str) or not name.strip() or not isinstance(key, str) or not key:
        fail("repository name and signing_key are required")
    publishers = config.get("publishers", {})
    if not isinstance(publishers, dict) or not publishers:
        fail("at least one publisher must be configured")
    for publisher_id, publisher in publishers.items():
        if not NAME.fullmatch(publisher_id) or not isinstance(publisher.get("public_key"), str):
            fail(f"invalid publisher configuration: {publisher_id}")
    apps = {}
    for name, item in config.get("apps", {}).items():
        if not NAME.fullmatch(name) or not isinstance(item, dict):
            fail(f"invalid app configuration: {name}")
        if type(item.get("enabled", False)) is not bool:
            fail(f"app enabled must be boolean: {name}")
        if not item.get("enabled", False):
            continue
        if item.get("mode", "maintained") not in ("maintained", "releases", "commits"):
            fail(f"invalid build mode for {name}")
        publisher = item.get("publisher")
        if publisher not in publishers:
            fail(f"unknown publisher for {name}")
        channel = item.get("channel", "stable")
        if channel not in ("stable", "testing"):
            fail(f"invalid channel for {name}")
        apps[name] = {"name": name, "publisher": publisher, "channel": channel,
                      "mode": item.get("mode", "maintained")}
    hours = config.get("server", {}).get("check_interval_hours", 6)
    if type(hours) not in (int, float) or not 1 <= hours <= 168:
        fail("check_interval_hours must be between 1 and 168")
    return repo, publishers, apps, float(hours)


def package_name(path):
    """Only for routing; this untrusted name never authorizes publication."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PACKAGE:
        fail(f"unsafe package file: {path}")
    with zipfile.ZipFile(path) as archive:
        if "manifest.toml" not in archive.namelist():
            fail("missing manifest.toml")
        if archive.getinfo("manifest.toml").file_size > 1024 * 1024:
            fail("oversized manifest")
        manifest = tomllib.loads(archive.read("manifest.toml").decode("utf-8"))
    return manifest.get("app", {}).get("name")


def permitted_package(path, apps, publishers, fingerprints):
    # The path and signed identity must agree. Nothing is published by wildcard.
    name = package_name(path)
    if name not in apps:
        fail(f"app not enabled or not configured: {name}")
    settings = apps[name]
    publisher_id = settings["publisher"]
    verified = validate_package(path, settings, publishers[publisher_id]["public_key"],
                                fingerprints[publisher_id])
    return verified


def collect(public, apps, publishers, fingerprints):
    root = public / "packages"
    packages = []
    if root.exists():
        for path in sorted(root.rglob("*.fre3app")):
            if package_name(path) not in apps:
                # Disabled apps disappear from the signed index; old archives
                # are retained for deliberate operator cleanup.
                continue
            verified = permitted_package(path, apps, publishers, fingerprints)
            if path.parent != root / verified["name"]:
                fail(f"incorrect published app path: {path}")
            verified["path"] = path.relative_to(public).as_posix()
            packages.append(verified)
    identities = set()
    for entry in packages:
        identity = (entry["publisher"]["id"], entry["name"],
                    entry["release_serial"] if entry["release_serial"] > 0 else entry["version"])
        if identity in identities:
            fail(f"duplicate published version/serial for {entry['name']}")
        identities.add(identity)
    return sorted(packages, key=lambda p: (p["name"], p["release_serial"], p["version"]))


def import_incoming(data, apps, publishers, fingerprints, existing):
    incoming = data / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    identities = {(p["publisher"]["id"], p["name"],
                   p["release_serial"] if p["release_serial"] > 0 else p["version"]): p
                  for p in existing}
    for candidate in sorted(incoming.glob("*.fre3app")):
        # A producer must publish complete incoming files by atomic rename.
        with tempfile.NamedTemporaryFile(prefix=".fre3app-", dir=data / "public",
                                         delete=False) as temporary:
            staged = Path(temporary.name)
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    fail(f"unsafe incoming package: {candidate}")
                if candidate.stat().st_size > MAX_PACKAGE:
                    fail(f"oversized incoming package: {candidate}")
                with candidate.open("rb") as source:
                    shutil.copyfileobj(source, temporary)
            except BaseException:
                staged.unlink(missing_ok=True)
                raise
        try:
            entry = permitted_package(staged, apps, publishers, fingerprints)
            identity = (entry["publisher"]["id"], entry["name"],
                        entry["release_serial"] if entry["release_serial"] > 0 else entry["version"])
            if identity in identities:
                if identities[identity]["sha256"] != entry["sha256"]:
                    fail(f"conflicting package identity: {entry['name']} {entry['version']}")
                candidate.unlink()
                staged.unlink()
                continue
            name = f"{entry['name']}-{entry['version']}-{entry['sha256'][:12]}.fre3app"
            destdir = data / "public" / "packages" / entry["name"]
            destdir.mkdir(parents=True, exist_ok=True)
            destination = destdir / name
            if destination.exists():
                fail(f"published destination exists unexpectedly: {destination}")
            staged.chmod(0o644)
            staged.replace(destination)
            candidate.unlink()
            entry["path"] = destination.relative_to(data / "public").as_posix()
            identities[identity] = entry
            print(f"published signed package: {entry['name']} {entry['version']}", flush=True)
        finally:
            staged.unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def publish_index(public, repository_name, key_fingerprint, private_key, packages):
    index_file = public / "index.json"
    signature_file = public / "index.json.sig"
    contents = {
        "schema": 1,
        "repository": {"name": repository_name, "key_fingerprint": key_fingerprint},
        "packages": packages,
    }
    revision = 0
    if index_file.exists():
        old = json.loads(index_file.read_text(encoding="utf-8"))
        revision = old.get("revision", 0)
        if type(revision) is not int or revision < 1:
            fail("invalid existing index revision")
        prior = {key: value for key, value in old.items() if key != "revision"}
        if prior == contents and signature_file.exists():
            return False
    contents["revision"] = revision + 1
    data = json_bytes(contents)
    signature = sign_index(private_key, data)
    public.mkdir(parents=True, exist_ok=True)
    # Each file is atomically replaced; a reader spanning a publication may
    # briefly see a mismatched pair and must reject/retry, never trust it.
    for destination, content in ((signature_file, signature), (index_file, data)):
        with tempfile.NamedTemporaryFile(dir=public, prefix=".index-", delete=False) as f:
            staged = Path(f.name)
            try:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                staged.unlink(missing_ok=True)
                raise
        staged.chmod(0o644)
        staged.replace(destination)
    print(f"published index revision {revision + 1} ({len(packages)} packages)", flush=True)
    return True


def execute(config_path, data):
    repo, publishers, apps, _ = load_config(config_path)
    data.mkdir(parents=True, exist_ok=True)
    public = data / "public"
    public.mkdir(parents=True, exist_ok=True)
    key = Path(repo["signing_key"])
    if not key.is_file():
        fail("repository signing key not available")
    fingerprint = public_fingerprint(key, private=True)
    public_keys = {name: value for name, value in publishers.items()}
    fingerprints = {name: public_fingerprint(value["public_key"])
                    for name, value in public_keys.items()}
    if fingerprint in fingerprints.values():
        fail("repository index key must differ from app publisher keys")
    existing = collect(public, apps, public_keys, fingerprints)
    import_incoming(data, apps, public_keys, fingerprints, existing)
    packages = collect(public, apps, public_keys, fingerprints)
    publish_index(public, repo["name"], fingerprint, key, packages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path(os.environ.get("REPOSITORY_CONFIG", "/config/config.toml")))
    parser.add_argument("--data", type=Path,
                        default=Path(os.environ.get("REPOSITORY_DATA", "/data")))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--loop", action="store_true")
    options = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    while not STOP.is_set():
        try:
            execute(options.config, options.data)
        except (RepositoryError, OSError, ValueError, zipfile.BadZipFile,
                tomllib.TOMLDecodeError) as error:
            print(f"repositoryd: {error}", file=sys.stderr, flush=True)
            if options.once:
                return 1
        if options.once:
            break
        try:
            _, _, _, hours = load_config(options.config)
        except (RepositoryError, OSError, ValueError) as error:
            print(f"repositoryd: invalid config: {error}", file=sys.stderr, flush=True)
            return 1
        STOP.wait(hours * 3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
