"""Offline fixtures: no network, signing, key generation or target builds."""

import base64
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

RECIPE = Path(__file__).resolve().parents[1]
ROOT = RECIPE.parents[1]


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


client = load_module("app_update_client", RECIPE / "payload/client.py")
fetch_transport = client.fetch
worker = load_module("app_update_worker_contract", ROOT / "docker-repository/repositoryd.py")

# RFC 8032, section 7.1, TEST 2. Public material only, no signing seed.
PUBLIC = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
DER = client.SPKI_PREFIX + PUBLIC
FINGERPRINT = hashlib.sha256(DER).hexdigest()
SIGNATURE = bytes.fromhex(
    "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da08"
    "5ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")


def fake_signature(raw):
    """Token used only by the simulated index verifier, not an Ed25519 signature."""
    return hashlib.sha256(raw).digest() * 2


def index(revision=1):
    digest = "a" * 64
    return {"schema": 1, "revision": revision,
            "repository": {"name": "Fixture repository", "key_fingerprint": FINGERPRINT},
            "packages": [{"name": "example", "version": "1.0-fre3nder.1", "release_serial": 1,
                "publisher": {"id": "example-publisher", "key_fingerprint": "b" * 64},
                "target": {"platform": "fre3nder-x2000", "arch": "mipsel"},
                "channel": "stable", "size": 100, "sha256": digest,
                "path": f"packages/example/example-1.0-fre3nder.1-{digest[:12]}.fre3app"}]}


class ClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.raw = worker.json_bytes(index())
        self.signature = None
        self.public = self.patch(client, "public_key", return_value=(DER, FINGERPRINT))
        self.verify = self.patch(client, "verify_signature", side_effect=self.verify_fixture)
        self.fetch = self.patch(client, "fetch", side_effect=self.download)
        self.patch(client.STOP, "wait", return_value=False)
        client.STOP.clear()
        self.addCleanup(client.STOP.clear)
        network = mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.configure()

    def patch(self, target, name, **kwargs):
        patch = mock.patch.object(target, name, **kwargs)
        result = patch.start()
        self.addCleanup(patch.stop)
        return result

    def configure(self, **values):
        config = {"base_url": "https://repository.example.invalid/", "public_key": "repository-public.pem"}
        config.update(values)
        (self.data / "repository.json").write_text(json.dumps(config))

    def download(self, url, limit):
        self.assertIn(url.rsplit("/", 1)[1], ("index.json", "index.json.sig"))
        if url.endswith("index.json.sig"):
            return self.signature if self.signature is not None else fake_signature(self.raw)
        return self.raw

    def verify_fixture(self, der, raw, signature):
        self.assertEqual(der, DER)
        if signature != fake_signature(raw):
            raise client.SignatureError("fixture signature mismatch")

    def status(self):
        return json.loads((self.data / "status.json").read_text())

    def accept(self, revision=1):
        self.raw = worker.json_bytes(index(revision))
        self.assertEqual(client.check(self.data), "ok")
        return (self.data / "verified.json").read_bytes()

    def test_no_or_incomplete_configuration_never_contacts_network_or_key(self):
        path = self.data / "repository.json"
        path.unlink()
        for config in (None, {}, {"base_url": "https://repository.example.invalid/"},
                       {"public_key": "repository-public.pem"}, {"base_url": "", "public_key": "key"},
                       {"base_url": " ", "public_key": "key"}):
            with self.subTest(config=config):
                if config is not None:
                    path.write_text(json.dumps(config))
                self.assertEqual(client.check(self.data), "disabled")
                self.assertEqual(self.status()["configuration"], "unconfigured")
                self.assertIsNone(self.status()["error"])
                self.assertEqual(self.status()["packages"], [])
                self.assertFalse((self.data / "verified.json").exists())
        self.fetch.assert_not_called()
        self.public.assert_not_called()

    def test_accepts_actual_worker_schema_after_signature_verification(self):
        public = self.data / "public"
        with mock.patch.object(worker, "sign_index", side_effect=lambda key, raw: fake_signature(raw)):
            worker.publish_index(public, "Fixture repository", FINGERPRINT, Path("unused"), index()["packages"])
        self.raw = (public / "index.json").read_bytes()
        self.signature = (public / "index.json.sig").read_bytes()
        self.assertEqual(client.check(self.data), "ok")
        self.verify.assert_called_once_with(DER, self.raw, self.signature)
        cached = json.loads((self.data / "verified.json").read_text())
        self.assertEqual(cached["index"].encode(), self.raw)
        self.assertEqual(cached["signature"], self.signature.hex())
        status = self.status()
        self.assertEqual(status["revision"], 1)
        self.assertEqual(status["packages"], index()["packages"])
        self.assertEqual(status["repository"]["key_fingerprint"], FINGERPRINT)
        self.assertEqual(status["last_success"], cached["checked_at"])
        self.assertEqual([call.args[1] for call in self.fetch.call_args_list], [client.MAX_INDEX, 64])

    def test_unchanged_revision_is_valid_and_replay_floor_survives_configuration_removal(self):
        self.accept(3)
        self.assertEqual(client.check(self.data), "ok")
        before = (self.data / "verified.json").read_bytes()
        (self.data / "repository.json").unlink()
        self.assertEqual(client.check(self.data), "disabled")
        self.assertEqual((self.data / "verified.json").read_bytes(), before)
        self.configure()
        self.raw = worker.json_bytes(index(2))
        self.assertEqual(client.check(self.data), "error")
        self.assertIn("rollback", self.status()["error"])
        self.assertEqual(self.status()["revision"], 3)
        self.assertEqual((self.data / "verified.json").read_bytes(), before)

    def test_same_revision_requires_identical_signed_bytes(self):
        before = self.accept()
        self.raw += b" \n"
        self.assertEqual(client.check(self.data), "error")
        self.assertIn("same revision", self.status()["error"])
        self.assertEqual((self.data / "verified.json").read_bytes(), before)

    def test_invalid_signature_retries_only_once_and_preserves_last_good_state(self):
        before = self.accept()
        previous = self.status()
        self.fetch.reset_mock()
        self.signature = b"invalid".ljust(64, b"!")
        self.assertEqual(client.check(self.data), "error")
        self.assertEqual(self.fetch.call_count, 4)
        self.assertEqual((self.data / "verified.json").read_bytes(), before)
        self.assertEqual(self.status()["last_success"], previous["last_success"])
        self.assertEqual(self.status()["packages"], previous["packages"])

    def test_publication_mismatch_can_recover_on_second_signed_pair(self):
        old = self.raw
        new = worker.json_bytes(index(2))
        self.fetch.side_effect = [old, fake_signature(new), new, fake_signature(new)]
        self.assertEqual(client.check(self.data), "ok")
        self.assertEqual(self.status()["revision"], 2)
        self.assertEqual(self.fetch.call_count, 4)

    def test_claimed_repository_fingerprint_must_match_supplied_public_key(self):
        value = index()
        value["repository"]["key_fingerprint"] = "c" * 64
        self.raw = worker.json_bytes(value)
        self.assertEqual(client.check(self.data), "error")
        self.assertIn("fingerprint mismatch", self.status()["error"])
        self.assertFalse((self.data / "verified.json").exists())

    def test_key_change_cannot_silently_reset_revision_history(self):
        before = self.accept(3)
        self.public.return_value = (DER, "c" * 64)
        self.fetch.reset_mock()
        self.assertEqual(client.check(self.data), "error")
        self.fetch.assert_not_called()
        self.assertEqual((self.data / "verified.json").read_bytes(), before)
        self.assertEqual(self.status()["packages"], [])

    def test_failed_downloads_preserve_last_good_state(self):
        before = self.accept()
        for responses in ([OSError("offline")], [self.raw, OSError("interrupted signature")]):
            with self.subTest(responses=responses):
                self.fetch.side_effect = responses
                self.assertEqual(client.check(self.data), "error")
                self.assertEqual((self.data / "verified.json").read_bytes(), before)
                self.assertEqual(self.status()["packages"], index()["packages"])

    def test_modified_cached_index_bytes_are_rejected_while_repository_is_offline(self):
        self.accept(3)
        path = self.data / "verified.json"
        cached = json.loads(path.read_text())
        cached["index"] += " \n"
        path.write_bytes(client.json_bytes(cached))
        tampered = path.read_bytes()
        self.fetch.reset_mock()
        self.fetch.side_effect = OSError("offline")
        self.verify.reset_mock()
        self.assertEqual(client.check(self.data), "error")
        self.assertEqual(self.status()["packages"], [])
        self.assertIsNone(self.status()["revision"])
        self.assertIn("cached repository index signature", self.status()["error"])
        self.assertEqual(path.read_bytes(), tampered)
        self.fetch.assert_not_called()
        self.verify.assert_called_once_with(DER, cached["index"].encode("utf-8"),
                                            bytes.fromhex(cached["signature"]))

    def test_modified_cached_signature_is_rejected_while_repository_is_offline(self):
        self.accept(3)
        path = self.data / "verified.json"
        cached = json.loads(path.read_text())
        signature = bytearray.fromhex(cached["signature"])
        signature[0] ^= 1
        cached["signature"] = signature.hex()
        path.write_bytes(client.json_bytes(cached))
        tampered = path.read_bytes()
        self.fetch.reset_mock()
        self.fetch.side_effect = OSError("offline")
        self.verify.reset_mock()
        self.assertEqual(client.check(self.data), "error")
        self.assertEqual(self.status()["packages"], [])
        self.assertIsNone(self.status()["revision"])
        self.assertIn("cached repository index signature", self.status()["error"])
        self.assertEqual(path.read_bytes(), tampered)
        self.fetch.assert_not_called()
        self.verify.assert_called_once_with(DER, cached["index"].encode("utf-8"), bytes(signature))

    def test_failed_atomic_replacement_keeps_prior_index_and_removes_temporary(self):
        before = self.accept()
        self.raw = worker.json_bytes(index(2))
        replace = os.replace

        def fail_index(source, destination):
            if Path(destination).name == "verified.json":
                raise OSError("fixture disk failure")
            return replace(source, destination)

        with mock.patch.object(client.os, "replace", side_effect=fail_index):
            self.assertEqual(client.check(self.data), "error")
        self.assertEqual((self.data / "verified.json").read_bytes(), before)
        self.assertEqual(self.status()["revision"], 1)
        self.assertEqual(list(self.data.glob(".verified.json-*")), [])

    def test_status_write_failure_does_not_lose_committed_replay_floor(self):
        self.accept()
        self.raw = worker.json_bytes(index(2))
        replace = os.replace

        def fail_status(source, destination):
            if Path(destination).name == "status.json":
                raise OSError("fixture status write failure")
            return replace(source, destination)

        with mock.patch.object(client.os, "replace", side_effect=fail_status):
            with self.assertRaises(OSError):
                client.check(self.data)
        self.raw = worker.json_bytes(index(1))
        self.assertEqual(client.check(self.data), "error")
        self.assertEqual(self.status()["revision"], 2)
        self.assertEqual(list(self.data.glob(".status.json-*")), [])

    def test_invalid_configuration_or_corrupt_cache_fails_before_network(self):
        for url in ("file:///index", "https://fixture:invalid@repository.example.invalid/",
                    "https://repository.example.invalid/?token=fixture", "https://repository.example.invalid/#index",
                    "https://repository.example.invalid:invalid/"):
            with self.subTest(url=url):
                self.configure(base_url=url)
                self.assertEqual(client.check(self.data), "error")
                self.fetch.assert_not_called()
        self.configure()
        (self.data / "verified.json").write_text('{"schema":1,"key_fingerprint":"' + FINGERPRINT + '","index":3}')
        self.assertEqual(client.check(self.data), "error")
        self.fetch.assert_not_called()

    def test_package_metadata_and_paths_are_validated_after_signature(self):
        mutations = (("name", "../other"), ("version", "1/../../evil"), ("version", "v 1"),
            ("release_serial", True), ("release_serial", -1), ("release_serial", 0),
            ("publisher", {"id": "bad/name", "key_fingerprint": "b" * 64}),
            ("publisher", {"id": "publisher", "key_fingerprint": "invalid"}),
            ("target", {"platform": "other", "arch": "mipsel"}), ("channel", "unknown"),
            ("size", True), ("size", 0), ("size", 256 * 1024 * 1024 + 1), ("sha256", "A" * 64),
            *(("path", path) for path in ("/absolute.fre3app", "../evil.fre3app", "https://elsewhere.invalid/a.fre3app",
               "packages/example/../../evil.fre3app", "packages/example/a%2f..%2fevil.fre3app",
               "packages/example/a\\evil.fre3app", "//elsewhere.invalid/a.fre3app", "a.fre3app?download=1")))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                document = index()
                document["packages"][0][field] = value
                self.raw = worker.json_bytes(document)
                self.assertEqual(client.check(self.data), "error")
                self.assertFalse((self.data / "verified.json").exists())

    def test_schema_revision_duplicates_and_development_offers(self):
        for field, value in (("schema", True), ("schema", 2), ("revision", True), ("revision", 0),
                             ("repository", None), ("packages", {}),
                             ("packages", index()["packages"] * 2)):
            with self.subTest(field=field):
                document = index()
                document[field] = value
                self.raw = worker.json_bytes(document)
                self.assertEqual(client.check(self.data), "error")
        self.raw = b'{"schema":1,"schema":1}'
        self.assertEqual(client.check(self.data), "error")
        document = index()
        document["packages"][0].update(release_serial=0, channel="testing")
        self.raw = worker.json_bytes(document)
        self.assertEqual(client.check(self.data), "ok")

    def test_status_contains_only_validated_offer_fields(self):
        document = index()
        document["repository"]["extension"] = "\ud800"
        document["packages"][0]["publisher"]["extension"] = "\ud800"
        document["packages"][0]["extension"] = {"unvalidated": "\ud800"}
        self.raw = json.dumps(document, ensure_ascii=True).encode()
        self.assertEqual(client.check(self.data), "ok")
        self.assertEqual(self.status()["packages"], index()["packages"])
        self.assertNotIn("extension", self.status()["repository"])
        self.assertEqual(json.loads((self.data / "verified.json").read_text())["index"].encode(), self.raw)

    def package_download_fixture(self, package=b"package-bytes" * 7000):
        value = index()
        offer = value["packages"][0]
        offer.update(size=len(package), sha256=hashlib.sha256(package).hexdigest())
        offer["path"] = f"packages/example/example-{offer['version']}-{offer['sha256'][:12]}.fre3app"
        raw = worker.json_bytes(value)
        (self.data / "verified.json").write_bytes(client.json_bytes({
            "schema": 1, "key_fingerprint": FINGERPRINT, "index": raw.decode(),
            "signature": fake_signature(raw).hex(), "checked_at": "2026-10-20T10:00:00+00:00"}))
        response = io.BytesIO(package)
        response.status, response.headers = 200, {}
        opener = mock.Mock()
        opener.open.return_value = response
        self.patch(client.urllib.request, "build_opener", return_value=opener)
        self.fetch.side_effect = fetch_transport
        return value, opener

    def test_explicit_download_reverifies_index_streams_bytes_and_creates_no_package_copy(self):
        package = b"package-bytes" * 7000
        value, opener = self.package_download_fixture(package)
        before = {path.name: path.read_bytes() for path in self.data.iterdir()}
        output, metadata = io.BytesIO(), io.BytesIO()
        client.download(self.data, "example", 1, output, metadata)
        self.assertEqual(output.getvalue(), package)
        self.assertEqual(json.loads(metadata.getvalue()), value["packages"][0])
        self.verify.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://repository.example.invalid/" + value["packages"][0]["path"])
        self.assertEqual({path.name: path.read_bytes() for path in self.data.iterdir()}, before)

    def test_download_rejects_absent_ambiguous_or_tampered_signed_offer(self):
        for failure in ("signature", "path", "ambiguous", "absent", "unconfigured"):
            with self.subTest(failure=failure):
                value, opener = self.package_download_fixture()
                cached = json.loads((self.data / "verified.json").read_text())
                if failure == "signature":
                    cached["signature"] = "0" * 128
                if failure == "path":
                    value["packages"][0]["path"] = "../other.fre3app"
                if failure == "ambiguous":
                    value["packages"].append({**value["packages"][0], "publisher": {"id": "other", "key_fingerprint": "e" * 64}})
                if failure in ("path", "ambiguous"):
                    cached["index"] = worker.json_bytes(value).decode()
                    cached["signature"] = fake_signature(cached["index"].encode()).hex()
                (self.data / "verified.json").write_bytes(client.json_bytes(cached))
                if failure == "unconfigured":
                    (self.data / "repository.json").unlink()
                output = io.BytesIO()
                with self.assertRaises(client.ClientError):
                    client.download(self.data, "missing" if failure == "absent" else "example", 1, output)
                self.assertEqual(output.getvalue(), b"")
                opener.open.assert_not_called()

    def test_download_transport_checks_size_digest_and_interruption(self):
        for failure in ("size", "digest", "interrupted", "redirect", "encoding"):
            with self.subTest(failure=failure):
                _, opener = self.package_download_fixture(b"abc")
                response = io.BytesIO(b"abd" if failure == "digest" else b"ab" if failure == "size" else b"abc")
                response.status = 302 if failure == "redirect" else 200
                response.headers = {"Content-Encoding": "gzip"} if failure == "encoding" else {}
                if failure == "interrupted":
                    response.read1 = mock.Mock(side_effect=OSError("connection interrupted"))
                opener.open.return_value = response
                with self.assertRaises((client.ClientError, OSError)):
                    client.download(self.data, "example", 1, io.BytesIO())

    def test_download_cli_uses_stdout_only_for_bytes_and_stderr_for_failures(self):
        self.package_download_fixture(b"abc")
        output, errors = io.BytesIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["client", "--data", str(self.data), "--download", "example", "--release-serial", "1"]), \
                mock.patch.object(sys, "stdout", buffer=output), mock.patch.object(sys, "stderr", errors), \
                mock.patch.object(client.signal, "signal"), mock.patch.object(client.os, "umask"):
            self.assertEqual(client.main(), 0)
        self.assertEqual(output.getvalue(), b"abc")
        self.assertEqual(errors.getvalue(), "")
        self.package_download_fixture(b"abc")
        with mock.patch.object(sys, "argv", ["client", "--data", str(self.data), "--download", "../bad", "--release-serial", "1"]), \
                mock.patch.object(sys, "stdout", buffer=io.BytesIO()) as stdout, mock.patch.object(sys, "stderr", errors), \
                mock.patch.object(client.signal, "signal"), mock.patch.object(client.os, "umask"):
            self.assertEqual(client.main(), 1)
            self.assertEqual(stdout.buffer.getvalue(), b"")
        self.assertIn("app name", errors.getvalue())

    def test_background_loop_keeps_errors_in_process_and_uses_bounded_retry(self):
        for outcome, interval in (("ok", 1800), ("error", 60), ("disabled", 60)):
            with self.subTest(outcome=outcome):
                client.STOP.clear()
                with mock.patch.object(client.sys, "argv", ["client", "--data", str(self.data)]), \
                        mock.patch.object(client.signal, "signal"), \
                        mock.patch.object(client, "check", return_value=outcome) as check, \
                        mock.patch.object(client.STOP, "wait", side_effect=lambda seconds: client.STOP.set()) as wait:
                    self.assertEqual(client.main(), 0)
                check.assert_called_once_with(self.data)
                wait.assert_called_once_with(interval)
                self.assertFalse((self.data / "client.pid").exists())


class CryptoAndTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        client.STOP.clear()
        patch = mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_openssl_public_fixture_and_exact_bytes_verification(self):
        pem = b"-----BEGIN PUBLIC KEY-----\n" + base64.b64encode(DER) + b"\n-----END PUBLIC KEY-----\n"
        key = self.data / "public.pem"
        key.write_bytes(pem)
        self.assertEqual(client.public_key(key), (DER, FINGERPRINT))
        client.verify_signature(DER, b"\x72", SIGNATURE)
        for raw, signature in ((b"\x73", SIGNATURE), (b"\x72", b"x" * 64), (b"\x72", b"x" * 63)):
            with self.subTest(raw=raw, signature_length=len(signature)):
                with self.assertRaises(client.SignatureError):
                    client.verify_signature(DER, raw, signature)
        other = client.SPKI_PREFIX + bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        with self.assertRaises(client.SignatureError):
            client.verify_signature(other, b"\x72", SIGNATURE)

    def test_missing_or_invalid_public_key_is_rejected(self):
        with self.assertRaises(OSError):
            client.public_key(self.data / "missing.pem")
        path = self.data / "invalid.pem"
        path.write_bytes(b"fixture, not a public key")
        with self.assertRaises(client.ClientError):
            client.public_key(path)

    def response(self, raw, headers=None, status=200):
        response = io.BytesIO(raw)
        response.headers = headers or {}
        response.status = status
        return response

    def test_transport_bounds_size_timeout_and_partial_responses_without_network(self):
        for response, limit, success in (
            (self.response(b"abc", {"Content-Length": "3"}), 3, True),
            (self.response(b"abc"), 3, True),
            (self.response(b"abcd"), 3, False),
            (self.response(b"abc", {"Content-Length": "4"}), 3, False),
            (self.response(b"ab", {"Content-Length": "3"}), 3, False),
            (self.response(b"abc", {"Content-Encoding": "gzip"}), 3, False),
            (self.response(b"abc", status=206), 3, False),
        ):
            with self.subTest(response=response, success=success):
                opener = mock.Mock()
                opener.open.return_value = response
                with mock.patch.object(client.urllib.request, "build_opener", return_value=opener):
                    if success:
                        self.assertEqual(client.fetch("https://repository.example.invalid/index.json", limit), b"abc")
                    else:
                        with self.assertRaises(client.ClientError):
                            client.fetch("https://repository.example.invalid/index.json", limit)
                self.assertEqual(opener.open.call_args.kwargs["timeout"], client.TIMEOUT)
        self.assertIsNone(client.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_response_body_deadline(self):
        opener = mock.Mock()
        opener.open.return_value = self.response(b"abc")
        with mock.patch.object(client.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(client.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaisesRegex(client.ClientError, "deadline"):
                client.fetch("https://repository.example.invalid/index.json", 3)


class RecipeAndServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.env = dict(os.environ, FRE3NDER_APP_RUNTIME_DIR=str(RECIPE),
                        FRE3NDER_APP_DATA_DIR=str(self.data), FRE3NDER_PYTHON=sys.executable,
                        PYTHONDONTWRITEBYTECODE="1", PATH=os.environ["PATH"] + ":/usr/sbin:/sbin")
        self.addCleanup(lambda: self.service("stop"))

    def service(self, action):
        return subprocess.run([str(RECIPE / "service"), action], env=self.env, text=True,
                              capture_output=True, timeout=5)

    def wait_for_status(self):
        for _ in range(100):
            if (self.data / "status.json").exists():
                return json.loads((self.data / "status.json").read_text())
            time.sleep(0.02)
        self.fail("daemon did not report status")

    def test_lifecycle_is_idempotent_nonblocking_and_preserves_operator_data(self):
        for action in ("install", "update", "restore"):
            result = self.service(action)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.data / "status.json").exists())
        self.assertNotEqual(self.service("status").returncode, 0)
        self.assertEqual(self.service("start").returncode, 0)
        pid = (self.data / "client.pid").read_text()
        self.assertEqual(self.wait_for_status()["check"], "disabled")
        self.assertEqual(self.service("start").returncode, 0)
        self.assertEqual((self.data / "client.pid").read_text(), pid)
        self.assertEqual(self.service("status").returncode, 0)
        # --once must not compete with the daemon or reset accepted state.
        once = subprocess.run([sys.executable, str(RECIPE / "payload/client.py"), "--data", str(self.data), "--once"],
                              capture_output=True, text=True, timeout=5)
        self.assertNotEqual(once.returncode, 0)
        self.assertIn("already running", once.stderr)
        for action in ("stop", "stop", "uninstall"):
            self.assertEqual(self.service(action).returncode, 0)
        self.assertNotEqual(self.service("status").returncode, 0)
        self.assertFalse((self.data / "client.pid").exists())
        (self.data / "operator-file").write_text("retained fixture")
        self.assertEqual(self.service("start").returncode, 0)
        self.assertEqual(self.service("uninstall").returncode, 0)
        self.assertEqual((self.data / "operator-file").read_text(), "retained fixture")

    def test_stale_pid_does_not_stop_unrelated_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        self.addCleanup(process.wait)
        self.addCleanup(process.terminate)
        (self.data / "client.pid").write_text(str(process.pid))
        self.assertEqual(self.service("stop").returncode, 0)
        self.assertIsNone(process.poll())

    def test_check_errors_do_not_make_service_unhealthy_or_delay_start(self):
        (self.data / "repository.json").write_text(json.dumps({
            "base_url": "https://repository.example.invalid/", "public_key": "missing-fixture.pem"}))
        started = time.monotonic()
        result = self.service("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - started, 3)
        status = self.wait_for_status()
        self.assertEqual(status["check"], "error")
        self.assertEqual(self.service("status").returncode, 0)
        self.assertEqual(self.service("stop").returncode, 0)

    def test_preparer_selects_only_package_members_and_existing_manifest_contract(self):
        output = self.data / "package"
        result = subprocess.run([str(RECIPE / "scripts/prepare-fre3nder-app-update"), "--output", str(output)],
                                 capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()},
                         {"manifest.toml.in", "service", "payload/client.py", "licenses/LICENSE"})
        self.assertEqual((output / "payload/client.py").read_bytes(), (RECIPE / "payload/client.py").read_bytes())
        self.assertEqual((output / "licenses/LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())
        builder = load_module("app_update_package_contract", ROOT / "scripts/build-fre3app")
        manifest = builder.render_manifest(output, "b" * 64)
        self.assertIn(b'name = "fre3nder-app-update"', manifest)
        self.assertIn(b'autostart = true', manifest)


if __name__ == "__main__":
    unittest.main()
