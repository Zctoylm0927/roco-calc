#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页服务（server.py）的单元测试。

不启动固定端口：测试时用 0 号端口让系统临时分配，结束后关闭。
"""

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import roco_analysis as ra  # noqa: E402
import server  # noqa: E402


class QuietHandler(server.Handler):
    def log_message(self, format, *args):
        pass


class TestMeta(unittest.TestCase):
    def test_meta_counts(self):
        meta = server.build_meta()
        self.assertEqual(len(meta["pets"]), 621)
        self.assertEqual(len(meta["natures"]), 30)
        self.assertEqual(len(meta["skills"]), 358)
        for skill in meta["skills"]:
            self.assertIn(skill["damage_class"], ("物攻", "魔攻"))
            self.assertIsInstance(skill["power"], int)

    def test_meta_has_known_pets(self):
        names = {pet["name"] for pet in server.build_meta()["pets"]}
        self.assertIn("水灵", names)
        self.assertIn("龙息帕尔", names)


class TestAnalyzeRequest(unittest.TestCase):
    def test_initial_range(self):
        result = server.analyze_request(
            {
                "our_pet": {
                    "name": "水灵",
                    "nature": "聪明",
                    "talents": {"spa": 10},
                },
                "opponent_pet": {"name": "龙息帕尔"},
                "skill": "气泡",
            }
        )
        self.assertEqual(result["damage"]["min"], 140)
        self.assertEqual(result["damage"]["max"], 210)
        self.assertEqual(result["opponent"]["builds"]["total"], 46320)

    def test_invalid_payload(self):
        with self.assertRaises(ra.AnalysisError):
            server.analyze_request([])


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read()

    def post(self, path, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()

    def test_index_page(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("伤害范围", text)
        self.assertIn("/app.js", text)

    def test_meta_endpoint(self):
        status, body = self.get("/api/meta")
        self.assertEqual(status, 200)
        meta = json.loads(body.decode("utf-8"))
        self.assertEqual(len(meta["pets"]), 621)

    def test_analyze_endpoint(self):
        status, body = self.post(
            "/api/analyze",
            {
                "our_pet": {
                    "name": "水灵",
                    "nature": "聪明",
                    "talents": {"spa": 10},
                },
                "opponent_pet": {"name": "龙息帕尔"},
                "skill": "气泡",
            },
        )
        self.assertEqual(status, 200)
        result = json.loads(body.decode("utf-8"))
        self.assertEqual(result["damage"]["min"], 140)

    def test_analyze_error_returns_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(
                "/api/analyze",
                {
                    "our_pet": {"name": "不存在的精灵"},
                    "opponent_pet": {"name": "龙息帕尔"},
                    "skill": "气泡",
                },
            )
        self.assertEqual(ctx.exception.code, 400)
        error = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("找不到精灵", error["error"])


if __name__ == "__main__":
    unittest.main()
