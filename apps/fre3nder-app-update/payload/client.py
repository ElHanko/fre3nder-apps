#!/usr/bin/env python3
"""Optional, unprivileged discovery of signed schema-1 repository offers.

These files are advisory app data, never authorization for an installation.
Copyright (C) 2026 Fre3nder contributors; AGPL-3.0-or-later.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

MAX_INDEX = 1024 * 1024
TIMEOUT = 10
INTERVAL = 30 * 60
RETRY_INTERVAL = 60
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
HASH = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
PUBLISHER = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}\Z")
STOP = threading.Event()


class ClientError(Exception):
    pass


class SignatureError(ClientError):
    pass


def fail(message):
    raise ClientError(message)


def json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate JSON member")
        result[key] = value
    return result


def parse_json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=json_object,
                      parse_constant=lambda _: fail("non-finite JSON number"))


def read_file(path, limit):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        fail(f"expected regular file: {path.name}")
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        fail(f"oversized file: {path.name}")
    return raw


def atomic_write(path, raw):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as out:
        temporary = Path(out.name)
        try:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_config(data):
    path = data / "repository.json"
    if not path.exists() and not path.is_symlink():
        return None
    config = parse_json(read_file(path, 16 * 1024))
    if not isinstance(config, dict):
        fail("repository configuration must be an object")
    url, key = config.get("base_url"), config.get("public_key")
    if (url in (None, "") or key in (None, "")
            or isinstance(url, str) and not url.strip()
            or isinstance(key, str) and not key.strip()):
        return None
    if not isinstance(url, str) or not isinstance(key, str) or not url.strip() or not key.strip():
        fail("base_url and public_key must be nonempty strings")
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)):
        fail("base_url must be an HTTP(S) URL without credentials, query or fragment")
    # Accessing port also rejects malformed port numbers before any request.
    parts.port
    return {"base_url": url.rstrip("/") + "/", "public_key": data / key}


def public_key(path):
    raw = read_file(path, 16 * 1024)
    result = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"],
                            input=raw, capture_output=True, timeout=TIMEOUT)
    der = result.stdout
    if result.returncode or len(der) != 44 or not der.startswith(SPKI_PREFIX):
        fail("repository public key must be Ed25519")
    return der, hashlib.sha256(der).hexdigest()


def verify_signature(der, raw, signature):
    if len(signature) != 64:
        raise SignatureError("invalid Ed25519 signature length")
    with tempfile.TemporaryDirectory(prefix="fre3nder-index-verify-") as temp:
        temp = Path(temp)
        (temp / "key.der").write_bytes(der)
        (temp / "index").write_bytes(raw)
        (temp / "signature").write_bytes(signature)
        result = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
            "-keyform", "DER", "-inkey", str(temp / "key.der"), "-in", str(temp / "index"),
            "-sigfile", str(temp / "signature")], capture_output=True, timeout=TIMEOUT)
    if result.returncode:
        raise SignatureError("repository index signature verification failed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, limit):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity",
        "Cache-Control": "no-cache", "User-Agent": "fre3nder-app-update/0.1"})
    deadline = time.monotonic() + 3 * TIMEOUT
    with opener.open(request, timeout=TIMEOUT) as response:
        if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
            fail("unexpected index HTTP response")
        length = response.headers.get("Content-Length")
        expected = int(length) if length is not None else None
        if expected is not None and not 0 <= expected <= limit:
            fail("oversized index response")
        chunks, size = [], 0
        while True:
            if STOP.is_set():
                fail("check interrupted")
            if time.monotonic() > deadline:
                fail("index response deadline exceeded")
            chunk = response.read1(min(65536, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                fail("oversized index response")
            chunks.append(chunk)
        if expected is not None and size != expected:
            fail("incomplete index response")
        return b"".join(chunks)


def validate_index(raw, fingerprint):
    index = parse_json(raw)
    if not isinstance(index, dict) or type(index.get("schema")) is not int or index["schema"] != 1:
        fail("unsupported repository index schema")
    if type(index.get("revision")) is not int or index["revision"] < 1:
        fail("invalid index revision")
    repository = index.get("repository")
    if (not isinstance(repository, dict) or repository.get("key_fingerprint") != fingerprint
            or not isinstance(repository.get("name"), str) or not repository["name"].strip()
            or len(repository["name"]) > 128 or not repository["name"].isprintable()):
        fail("repository identity or key fingerprint mismatch")
    packages = index.get("packages")
    if not isinstance(packages, list) or len(packages) > 4096:
        fail("invalid package offers")
    identities = set()
    for item in packages:
        if not isinstance(item, dict):
            fail("invalid package metadata")
        name, version = item.get("name"), item.get("version")
        publisher, serial = item.get("publisher"), item.get("release_serial")
        digest, size = item.get("sha256"), item.get("size")
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or not isinstance(version, str) or not VERSION.fullmatch(version)
                or type(serial) is not int or serial < 0
                or not isinstance(publisher, dict) or not isinstance(publisher.get("id"), str)
                or not PUBLISHER.fullmatch(publisher["id"])
                or not isinstance(publisher.get("key_fingerprint"), str)
                or not HASH.fullmatch(publisher["key_fingerprint"])
                or item.get("target") != {"platform": "fre3nder-x2000", "arch": "mipsel"}
                or item.get("channel") not in ("stable", "testing")
                or serial == 0 and item["channel"] != "testing"
                or type(size) is not int or not 0 < size <= 256 * 1024 * 1024
                or not isinstance(digest, str) or not HASH.fullmatch(digest)):
            fail("invalid package metadata")
        expected_path = f"packages/{name}/{name}-{version}-{digest[:12]}.fre3app"
        if item.get("path") != expected_path:
            fail("invalid relative package path")
        identity = (publisher["id"], name, serial if serial > 0 else version)
        if identity in identities:
            fail("duplicate package release identity")
        identities.add(identity)
    return index


def cached_index(data, fingerprint, der):
    path = data / "verified.json"
    if not path.exists() and not path.is_symlink():
        return None
    cached = parse_json(read_file(path, 3 * MAX_INDEX + 4096))
    if (not isinstance(cached, dict) or type(cached.get("schema")) is not int or cached["schema"] != 1
            or cached.get("key_fingerprint") != fingerprint):
        fail("cached repository identity changed; explicitly reset verified.json to change keys")
    if (not isinstance(cached.get("index"), str) or not isinstance(cached.get("checked_at"), str)
            or not isinstance(cached.get("signature"), str)
            or not re.fullmatch(r"[0-9a-f]{128}", cached["signature"])):
        fail("invalid cached repository index")
    raw = cached["index"].encode("utf-8")
    if len(raw) > MAX_INDEX:
        fail("oversized cached index")
    try:
        verify_signature(der, raw, bytes.fromhex(cached["signature"]))
    except SignatureError as exc:
        raise SignatureError("cached repository index signature verification failed") from exc
    validate_index(raw, fingerprint)
    return cached


def check(data):
    config, cached, fingerprint = None, None, None
    configuration = "invalid"
    attempted = datetime.now(timezone.utc).isoformat()
    outcome, error = "error", None
    try:
        config = load_config(data)
        if config is None:
            configuration, outcome = "unconfigured", "disabled"
        else:
            configuration = "configured"
            der, fingerprint = public_key(config["public_key"])
            cached = cached_index(data, fingerprint, der)
            for attempt in range(2):
                raw = fetch(config["base_url"] + "index.json", MAX_INDEX)
                signature = fetch(config["base_url"] + "index.json.sig", 64)
                try:
                    verify_signature(der, raw, signature)
                    break
                except SignatureError:
                    if attempt or STOP.wait(1):
                        raise
            index = validate_index(raw, fingerprint)
            if cached is not None:
                previous = validate_index(cached["index"].encode("utf-8"), fingerprint)
                if index["revision"] < previous["revision"]:
                    fail("index revision rollback rejected")
                if index["revision"] == previous["revision"] and raw != cached["index"].encode("utf-8"):
                    fail("index bytes changed under the same revision")
            accepted = {"schema": 1, "key_fingerprint": fingerprint, "index": raw.decode("utf-8"),
                        "signature": signature.hex(), "checked_at": attempted}
            atomic_write(data / "verified.json", json_bytes(accepted))
            cached, outcome = accepted, "ok"
    except (ClientError, OSError, ValueError, KeyError, TypeError, RecursionError,
            http.client.HTTPException, subprocess.SubprocessError) as exc:
        error = str(exc)[:256]
    index = validate_index(cached["index"].encode("utf-8"), fingerprint) if cached else None
    repository = {"key_fingerprint": fingerprint, "name": index["repository"]["name"] if index else None}
    if config:
        repository["base_url"] = config["base_url"]
    offers = []
    for item in index["packages"] if index else []:
        offer = {key: item[key] for key in ("name", "version", "release_serial", "channel",
                                           "target", "sha256", "path", "size")}
        offer["publisher"] = {key: item["publisher"][key] for key in ("id", "key_fingerprint")}
        offers.append(offer)
    status = {"schema": 1, "configuration": configuration, "check": outcome, "error": error,
              "repository": repository if config else None,
              "revision": index["revision"] if index else None,
              "last_attempt": attempted if config else None,
              "last_success": cached["checked_at"] if cached else None, "packages": offers}
    atomic_write(data / "status.json", json_bytes(status))
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="check once, without package downloads")
    args = parser.parse_args()
    os.umask(0o077)
    args.data.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    with (args.data / "client.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "fre3nder-app-update: a check process is already running\n")
        pid = args.data / "client.pid"
        if not args.once:
            atomic_write(pid, f"{os.getpid()}\n".encode("ascii"))
        try:
            while not STOP.is_set():
                try:
                    outcome = check(args.data)
                except OSError as exc:
                    print(f"fre3nder-app-update: cannot persist status: {exc}", file=sys.stderr, flush=True)
                    outcome = "error"
                if args.once:
                    return int(outcome == "error")
                STOP.wait(INTERVAL if outcome == "ok" else RETRY_INTERVAL)
        finally:
            if not args.once:
                pid.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
