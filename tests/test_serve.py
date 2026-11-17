import concurrent.futures
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from serve import Presentation, PresentationServer


SOURCE = """---
presentation-title: Test LAN
timer: 0.05
---
---title
title: Welcome
>> PRIVATE_FIRST
---content
title: Second
>> PRIVATE_SECOND
Body
---content
title: Hidden
hidden: true
>> PRIVATE_HIDDEN
---closing
title: End
>> PRIVATE_LAST
"""


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "deck.md"
        self.source.write_text(SOURCE, encoding="utf-8")
        self.presentation = Presentation(self.source, "")
        self.server = PresentationServer(("127.0.0.1", 0), self.presentation, "127.0.0.1")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, payload=None, cookie=None, extra_headers=None):
        headers = {}
        if payload is not None:
            headers.update({"Content-Type": "application/json", "Origin": f"http://{self.host}", "X-Mdslides": "1"})
        if cookie:
            headers["Cookie"] = cookie
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("GET" if payload is None else "POST", path,
                               body=None if payload is None else json.dumps(payload), headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def login(self, token=False):
        credential = {"token": self.presentation.qr_token} if token else {"password": self.presentation.password}
        status, headers, _ = self.request("/api/auth", credential)
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";")[0]

    def state(self, cookie=None):
        status, _, body = self.request("/api/state", cookie=cookie)
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_public_html_and_state_do_not_contain_notes_or_hidden_slides(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"PRIVATE_", body)
        self.assertNotIn(b">Hidden<", body)
        self.assertIn(b'/client.js', body)
        state = self.state()
        self.assertNotIn("notes", state)
        self.assertEqual(state["total"], 3)
        self.assertFalse(state["authorized"])

    def test_password_and_qr_login_expose_current_private_notes(self):
        for token in (False, True):
            with self.subTest(token=token):
                cookie = self.login(token)
                self.assertEqual(self.state(cookie)["notes"], ["PRIVATE_FIRST"])
                self.assertNotIn("notes", self.state())

    def test_unauthenticated_commands_and_invalid_credentials_are_rejected(self):
        self.assertEqual(self.request("/api/command", {"action": "next"})[0], 401)
        for payload in ({"password": "wrong"}, {"token": "wrong"}, {"password": ["invalid"]}, {"password": "é"}):
            self.assertEqual(self.request("/api/auth", payload)[0], 401)
        self.assertEqual(self.state()["index"], 0)

    def test_login_is_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self.request("/api/auth", {"password": "wrong"})[0], 401)
        self.assertEqual(self.request("/api/auth", {"password": self.presentation.password})[0], 429)
        self.presentation.failures["127.0.0.1"] = (10, time.monotonic() - 61)
        self.login()

    def test_all_controllers_and_viewers_share_slide_and_timer_state(self):
        first, second = self.login(), self.login(True)
        self.assertFalse(self.state()["running"])
        self.assertEqual(self.request("/api/command", {"action": "next"}, first)[0], 200)
        for cookie in (None, first, second):
            state = self.state(cookie)
            self.assertEqual(state["index"], 1)
            self.assertTrue(state["running"])
            self.assertEqual(state["duration"], 3)
        self.assertEqual(self.state(second)["notes"], ["PRIVATE_SECOND"])
        self.request("/api/command", {"action": "last"}, second)
        self.assertEqual(self.state(first)["index"], 2)
        self.request("/api/command", {"action": "next"}, first)
        self.assertEqual(self.state()["index"], 2)
        self.request("/api/command", {"action": "previous"}, first)
        self.assertEqual(self.state()["index"], 1)
        self.request("/api/command", {"action": "first"}, second)
        self.assertEqual(self.state()["index"], 0)
        self.assertTrue(self.state()["running"])

    def test_timer_reset_and_expiry_use_server_monotonic_clock(self):
        with patch("serve.time.monotonic", return_value=100):
            self.presentation.command({"action": "next"})
        with patch("serve.time.monotonic", return_value=102):
            self.assertEqual(self.presentation.snapshot(False)["elapsed"], 2)
            self.presentation.command({"action": "reset_timer"})
            self.assertEqual(self.presentation.snapshot(False)["elapsed"], 0)
        with patch("serve.time.monotonic", return_value=107):
            self.assertEqual(self.presentation.snapshot(False)["elapsed"], 5)
            self.presentation.command({"action": "first"})
            self.presentation.command({"action": "reset_timer"})
            self.assertFalse(self.presentation.snapshot(False)["running"])

    def test_concurrent_next_commands_are_atomic(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.presentation.command({"action": "next"}), range(2)))
        self.assertEqual(self.state()["index"], 2)
        self.assertEqual(self.state()["revision"], 2)

    def test_invalid_commands_never_change_state(self):
        cookie = self.login()
        for payload in ({"action": "unknown"}, {"action": "goto", "index": -1},
                        {"action": "goto", "index": 3}, {"action": "goto", "index": True},
                        {"action": "goto", "index": "1"}, ["next"]):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("/api/command", payload, cookie)[0], 400)
        self.assertEqual(self.state()["revision"], 0)
        self.assertEqual(self.request("/api/command", {"action": "goto", "index": 2}, cookie)[0], 200)
        self.assertEqual(self.state()["index"], 2)

    def test_cross_origin_requests_and_rebinding_are_rejected(self):
        cookie = self.login()
        for headers in ({"Origin": "http://attacker.example"}, {"X-Mdslides": ""},
                        {"Host": f"attacker.example:{self.server.server_port}"}):
            self.assertEqual(self.request("/api/command", {"action": "next"}, cookie, headers)[0], 403)
        self.assertEqual(self.request("/api/state", extra_headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.state()["index"], 0)

    def test_only_explicit_web_routes_are_served(self):
        for path in ("/deck.md", "/generate.py", "/../deck.md", "/%2e%2e/README.md", "/assets/secret"):
            self.assertEqual(self.request(path)[0], 404)
        for path in ("/?mode=remote", "/?mode=presenter", "/client.js", "/remote.js"):
            self.assertEqual(self.request(path)[0], 200)

    def test_logout_invalidates_session(self):
        cookie = self.login()
        self.assertEqual(self.request("/api/logout", {}, cookie)[0], 200)
        self.assertNotIn("notes", self.state(cookie))
        self.assertEqual(self.request("/api/command", {"action": "next"}, cookie)[0], 401)

    def test_server_does_not_write_generated_html(self):
        self.assertFalse(self.source.with_suffix(".html").exists())

    def test_empty_or_only_hidden_presentation_is_rejected(self):
        self.source.write_text("---content\nhidden: true\ntitle: Hidden\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "visible"):
            Presentation(self.source, "")


if __name__ == "__main__":
    unittest.main()
