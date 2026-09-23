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
                self.assertEqual(search.load_api_key(), "test-key")
                with redirect_stdout(io.StringIO()) as out:
                    code = search.main(["search.py", "--has-key"])
                self.assertEqual(code, 0)
                self.assertIn('"hasKey": true', out.getvalue())
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
