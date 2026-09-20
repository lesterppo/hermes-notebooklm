#!/usr/bin/env python3
"""Offline unit tests for nlm_v3.py — no network, no upstream CLI.

Upstream (`notebooklm`) is faked by monkeypatching `nlm._run`, so these tests
pin the wrapper's own contract: argument plumbing (-n/--notebook), JSON shape,
and the parsing of every upstream payload the wrapper reads.

Run:  python3 -m pytest tests/ -q      (or: python3 tests/test_nlm_v3.py)
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("nlm", ROOT / "nlm_v3.py")
nlm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nlm)

# Tests must never touch the user's real cached notebook or output dir.
_TMP = Path(tempfile.mkdtemp(prefix="nlm-test-"))
nlm.OUT_DIR = _TMP
DEFAULT_NB = "default-nb-0001"
nlm._default_nb = lambda: DEFAULT_NB


class FakeUpstream:
    """Records the argv it was called with and replays canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, args, timeout=90):
        self.calls.append(list(args))
        for key, value in self.responses.items():
            if all(k in args for k in key.split()):
                if callable(value):
                    return value(args)
                return value if isinstance(value, tuple) else (value, "", 0)
        return ("{}", "", 0)

    def argv(self, index=-1):
        return self.calls[index]


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeUpstream()
        self._orig_run = nlm._run
        nlm._run = self.fake

    def tearDown(self):
        nlm._run = self._orig_run


class TestNotebookFlagPlumbing(Base):
    """-n must reach upstream. Ignoring it silently answered about the default
    notebook, which produced wrong answers (and a wrong share-status report)."""

    def assert_nb_forwarded(self, cmd, extra=None):
        out = cmd()
        argv = self.fake.argv()
        self.assertIn("--notebook", argv, f"notebook flag not forwarded: {argv}")
        i = argv.index("--notebook")
        self.assertEqual(argv[i + 1], "nb-other", argv)
        self.assertTrue(out)

    def test_split_nb_any_position(self):
        nb, rest = nlm._split_nb(["list", "-n", "abc", "--limit", "5"])
        self.assertEqual(nb, "abc")
        self.assertEqual(rest, ["list", "--limit", "5"])
        nb, rest = nlm._split_nb(["--notebook", "xyz", "add", "text"])
        self.assertEqual((nb, rest), ("xyz", ["add", "text"]))
        self.assertEqual(nlm._split_nb(["list"]), (None, ["list"]))

    def test_source_list(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_source_list(["-n", "nb-other"]))

    def test_source_get(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_source_get(["sid1", "-n", "nb-other"]))

    def test_source_guide(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_source_guide(["-n", "nb-other", "sid1"]))

    def test_source_fulltext(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_source_fulltext(["sid1", "-n", "nb-other"]))

    def test_source_delete(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_source_delete(["sid1", "-n", "nb-other"]))

    def test_artifact_list(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_artifact_list(["-n", "nb-other"]))

    def test_artifact_get(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_artifact_get(["aid1", "-n", "nb-other"]))

    def test_artifact_delete(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_artifact_delete(["-n", "nb-other", "aid1"]))

    def test_artifact_download(self):
        # download took no notebook at all before v7
        self.assert_nb_forwarded(lambda: nlm.cmd_artifact_download(["quiz", "-n", "nb-other"]))

    def test_note_list(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_note_list(["-n", "nb-other"]))

    def test_note_get(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_note_get(["nid1", "-n", "nb-other"]))

    def test_note_create(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_note_create(["-n", "nb-other", "-t", "T", "body"]))

    def test_share_status(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_share_status(["-n", "nb-other"]))

    def test_research_status(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_research_status(["-n", "nb-other"]))

    def test_configure(self):
        self.assert_nb_forwarded(lambda: nlm.cmd_configure(["-n", "nb-other"]))

    def test_ask(self):
        out = nlm.cmd_ask(["-n", "nb-other", "hello"])
        argv = self.fake.argv()
        self.assertIn("--notebook", argv)
        self.assertEqual(argv[argv.index("--notebook") + 1], "nb-other")

    def test_status_does_not_forward(self):
        # upstream `status` has no --notebook option — forwarding it errors out
        nlm.cmd_notebook_status(["-n", "nb-other"])
        self.assertNotIn("--notebook", self.fake.argv())


class TestParsing(unittest.TestCase):
    def setUp(self):
        nlm._run = lambda *a, **k: ("{}", "", 0)

    def tearDown(self):
        nlm._run = FakeUpstream()

    def test_artifact_get_url_from_poll(self):
        def responder(args):
            if "poll" in args:
                return (json.dumps({"result": {"url": "https://cdn/x.png"}}), "", 0)
            return (json.dumps({"artifact": {"id": "a1", "title": "T", "status": "completed"}}), "", 0)

        nlm._run = lambda args, timeout=30: responder(args)
        d = json.loads(nlm.cmd_artifact_get(["a1"]))
        self.assertEqual(d["url"], "https://cdn/x.png")
        self.assertEqual(d["id"], "a1")

    def test_share_status_shape(self):
        payload = json.dumps({"is_public": True, "access": "anyone_with_link",
                              "share_url": "https://n/x", "view_level": "full_notebook",
                              "shared_users": [{"email": "a@b.c", "permission": "owner",
                                                "display_name": "A"}]})
        nlm._run = lambda args, timeout=15: (payload, "", 0)
        d = json.loads(nlm.cmd_share_status([]))
        self.assertTrue(d["public"])
        self.assertEqual(d["users"][0]["email"], "a@b.c")

    def test_note_save_parsed(self):
        nlm._run = lambda args, timeout=30: (json.dumps({"id": "n1", "saved": True}), "", 0)
        d = json.loads(nlm.cmd_note_save(["n1", "hello"]))
        self.assertTrue(d["saved"])
        self.assertEqual(d["n_chars"], 5)

    def test_configure_preset_conflict_is_rejected_locally(self):
        d = json.loads(nlm.cmd_configure(["--mode", "concise", "--persona", "x"]))
        self.assertEqual(d["s"], "err")
        self.assertIn("cannot be combined", d["e"])

    def test_doctor_warn_is_not_a_failure(self):
        payload = json.dumps({"profile": "default", "checks": {
            "auth": {"status": "pass"}, "headless_reauth": {"status": "warn"}}})
        nlm._run = lambda args, timeout=60: (payload, "", 0)
        d = json.loads(nlm.cmd_doctor([]))
        self.assertTrue(d["healthy"])
        self.assertEqual(d["failing"], [])
        self.assertEqual(d["warnings"], ["headless_reauth"])

    def test_source_list_filters_forwarded(self):
        seen = {}
        def responder(args, timeout=30):
            seen["args"] = list(args)
            return (json.dumps({"sources": []}), "", 0)
        nlm._run = responder
        nlm.cmd_source_list(["--label", "L1", "--status", "ready", "--limit", "5"])
        for token in ("--label", "L1", "--status", "ready", "--limit", "5"):
            self.assertIn(token, seen["args"])

    def test_artifact_types_cover_upstream(self):
        for t in ("fantasy-map", "file", "cinematic-video"):
            self.assertIn(t, nlm.ARTIFACT_TYPES)


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.fake = FakeUpstream()
        nlm._run = self.fake

    def tearDown(self):
        nlm._run = FakeUpstream()

    def test_alias_src(self):
        nlm.dispatch(["src", "list"])
        self.assertEqual(self.fake.argv()[:2], ["source", "list"])

    def test_alias_gen(self):
        nlm.dispatch(["gen", "quiz", "desc"])
        self.assertIn("generate", self.fake.argv())

    def test_unknown_action_error(self):
        d = json.loads(nlm.dispatch(["source", "nope"]))
        self.assertEqual(d["s"], "err")
        self.assertIn("unknown action", d["e"])

    def test_group_without_action_error(self):
        d = json.loads(nlm.dispatch(["source"]))
        self.assertEqual(d["s"], "err")

    def test_free_text_falls_back_to_ask(self):
        self.fake.responses = {"ask": ("answer text", "", 0)}
        nlm.dispatch(["what", "is", "this"])
        self.assertEqual(self.fake.argv()[0], "ask")

    def test_surface_lists_new_groups(self):
        d = json.loads(nlm.dispatch(["surface"]))
        self.assertIn("source", d["groups"])
        self.assertIn("generate", d["groups"])
        self.assertIn("revise-slide", d["groups"]["generate"])

    def test_batch_runs_all(self):
        self.fake.responses = {"list": (json.dumps({"notebooks": []}), "", 0)}
        d = json.loads(nlm.dispatch(["batch", "nb list", "src list"]))
        self.assertEqual(d["n"], 2)
        self.assertEqual(d["n_ok"], 2)

    def test_no_args_prints_usage(self):
        self.assertIn("Usage", nlm.dispatch([]))


class TestBinaryResolution(unittest.TestCase):
    def test_env_override(self):
        fake = _TMP / "fake-notebooklm"
        fake.write_text("#!/bin/sh\n")
        os.environ["NOTEBOOKLM_CLI"] = str(fake)
        try:
            self.assertEqual(nlm._find_nlm(), str(fake))
        finally:
            os.environ.pop("NOTEBOOKLM_CLI")

    def test_falls_back_to_path_or_home(self):
        os.environ.pop("NOTEBOOKLM_CLI", None)
        got = nlm._find_nlm()
        self.assertTrue(got.endswith("notebooklm"), got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
