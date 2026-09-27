import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import search


def catalog(count):
    return [{"e": chr(0x1F600 + (i % 50)), "k": f"name {i}"} for i in range(count)]


class FakeResponse:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.stream.read(size)


class TrackingBytesIO(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class SearchTests(unittest.TestCase):
    def test_every_emoji_is_scored_once(self):
        previous = search.BATCH_SIZE
        search.BATCH_SIZE = 2
        try:
            items = catalog(5)
            calls = []
            lock = threading.Lock()

            def ask(body):
                with lock:
                    calls.append(body)
                self.assertEqual(body["state"], "party")
                answers = {}
                for key, question in body["questions"].items():
                    self.assertEqual(question["type"], "noul")
                    answers[key] = {"noul": 0.91 if key == "e3" else 0.2}
                return {"answers": answers}

            results = search.search("party", items, ask)
            seen = []
            for body in calls:
                seen.extend(body["questions"])
            self.assertEqual(sorted(seen), ["e0", "e1", "e2", "e3", "e4"])
            self.assertEqual(len(seen), len(set(seen)))
            self.assertEqual(len(calls), 3)
            self.assertEqual(results[0]["k"], "name 3")
            self.assertEqual(len(results), 1)
        finally:
            search.BATCH_SIZE = previous

    def test_real_catalog_batches_cover_every_emoji(self):
        items = search.tag_catalog(search.load_catalog(Path("emojis.json")))
        batches = search.chunk(items, search.BATCH_SIZE)
        self.assertEqual(sum(len(batch) for batch in batches), len(items))
        for batch in batches:
            raw = json.dumps(search.noul_request("birthday cake", batch))
            self.assertLess(len(raw), 150_000)

    def test_rank_drops_low_probability_and_sorts_high_first(self):
        candidates = [
            {"id": "e0", "emoji": "😀", "keywords": "grin"},
            {"id": "e1", "emoji": "😴", "keywords": "sleep"},
            {"id": "e2", "emoji": "🍕", "keywords": "pizza"},
        ]
        answers = {
            "e0": {"noul": 0.42},
            "e1": {"noul": 0.91},
            "e2": {"noul": 0.63},
        }
        ranked = search.rank_fits(candidates, answers)
        self.assertEqual([row["e"] for row in ranked], ["😴", "🍕"])
        self.assertGreater(ranked[0]["p"], ranked[1]["p"])

    def test_api_response_read_has_a_size_limit(self):
        response = FakeResponse(b"x" * (search.MAX_RESPONSE_BYTES + 1))
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "larger than 2 MiB"):
                search.post_systemone("test-key", {})
        self.assertEqual(response.read_sizes, [search.MAX_RESPONSE_BYTES + 1])

    def test_http_error_detail_read_has_a_size_limit(self):
        body = TrackingBytesIO(b"x" * (search.MAX_ERROR_DETAIL_BYTES + 1))
        error = search.urllib.error.HTTPError(
            search.API_URL,
            500,
            "Server error",
            {},
            body,
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "Jev returned HTTP 500"):
                search.post_systemone("test-key", {})
        self.assertEqual(body.read_sizes, [search.MAX_ERROR_DETAIL_BYTES])

    def test_save_key_is_private_and_loadable(self):
        env = os.environ.copy()
        try:
            os.environ.pop("TYPESAFE_API_KEY", None)
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["HOME"] = tmp
                self.assertFalse(search.has_api_key())
                with self.assertRaises(RuntimeError):
                    search.save_api_key("\n")
                search.save_api_key("  test-key  ")
                path = Path(tmp) / ".config" / "jev-emoji" / "api-key"
                self.assertEqual(path.read_text(encoding="utf-8"), "test-key")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(list(path.parent.glob("*.tmp")), [])
                self.assertEqual(search.load_api_key(), "test-key")
                with redirect_stdout(io.StringIO()) as out:
                    code = search.main(["search.py", "--has-key"])
                self.assertEqual(code, 0)
                self.assertIn('"hasKey": true', out.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_save_key_is_private_before_the_secret_is_written(self):
        env = os.environ.copy()
        real_open = os.open
        created = {}

        def tracking_open(path, flags, mode=0o777, *, dir_fd=None):
            descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            name = os.fsdecode(path)
            if name.endswith(".tmp"):
                info = os.fstat(descriptor)
                created["name"] = name
                created["mode"] = info.st_mode & 0o777
                created["inode"] = info.st_ino
            return descriptor

        try:
            os.environ.pop("TYPESAFE_API_KEY", None)
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["HOME"] = tmp
                previous_umask = os.umask(0)
                try:
                    with patch("os.open", tracking_open):
                        search.save_api_key("secret-key")
                finally:
                    os.umask(previous_umask)
                path = Path(tmp) / ".config" / "jev-emoji" / "api-key"
                self.assertEqual(created["mode"], 0o600)
                self.assertNotEqual(Path(created["name"]).name, "api-key.tmp")
                self.assertFalse(Path(created["name"]).exists())
                self.assertEqual(path.stat().st_ino, created["inode"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(encoding="utf-8"), "secret-key")
                self.assertEqual(list(path.parent.glob("*.tmp")), [])
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_save_key_command_reads_stdin(self):
        env = os.environ.copy()
        try:
            os.environ.pop("TYPESAFE_API_KEY", None)
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["HOME"] = tmp
                with patch("sys.stdin", io.StringIO("from-stdin\n")):
                    with redirect_stdout(io.StringIO()):
                        code = search.main(["search.py", "--save-key"])
                self.assertEqual(code, 0)
                self.assertEqual(search.load_api_key(), "from-stdin")
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_blank_query_does_not_ask(self):
        def ask(_body):
            raise AssertionError("blank query should not call Jev")

        self.assertEqual(search.search("   ", catalog(3), ask), [])


if __name__ == "__main__":
    unittest.main()
