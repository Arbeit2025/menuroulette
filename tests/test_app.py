import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["MENUROULETTE_DB"] = _tmp.name

import app as app_module  # noqa: E402


class MenuRouletteTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM custom_dishes")
            conn.execute("DELETE FROM history")
            conn.commit()

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_builtin_count(self):
        self.assertGreaterEqual(len(app_module.BUILTIN), 45)
        cats = {c for (_, c, _) in app_module.BUILTIN}
        self.assertEqual(cats, {"主菜", "副菜", "汁物"})

    def test_index_ok(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_draw_set(self):
        res = self.client.post("/draw", data={"mode": "set", "style": ""})
        body = res.get_data(as_text=True)
        self.assertIn("主菜：", body)
        self.assertIn("副菜：", body)
        self.assertIn("汁物：", body)
        with app_module.app.app_context():
            conn = app_module.get_db()
            n = conn.execute("SELECT COUNT(*) AS c FROM history").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_draw_single(self):
        res = self.client.post("/draw", data={"mode": "single", "style": ""})
        body = res.get_data(as_text=True)
        self.assertIn("主菜：", body)
        self.assertNotIn("副菜：", body)

    def test_style_filter(self):
        with app_module.app.app_context():
            conn = app_module.get_db()
            for _ in range(5):
                main = app_module.pick(conn, "主菜", "和")
                wa_mains = {n for (n, c, s) in app_module.BUILTIN if c == "主菜" and s == "和"}
                self.assertIn(main, wa_mains)

    def test_avoid_recent_deterministic(self):
        with app_module.app.app_context():
            conn = app_module.get_db()
            wa_mains = [n for (n, c, s) in app_module.BUILTIN if c == "主菜" and s == "和"]
            avoid = frozenset(wa_mains[:-1])
            main = app_module.pick(conn, "主菜", "和", avoid)
            self.assertEqual(main, wa_mains[-1])

    def test_custom_dish_add_delete(self):
        self.client.post("/dishes", data={"name": "特製カレー", "category": "主菜", "style": "洋"})
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute("SELECT * FROM custom_dishes").fetchone()
            self.assertIsNotNone(row)
            did = row["id"]
            names = [n for (n, _, _) in app_module.all_dishes(conn)]
        self.assertIn("特製カレー", names)
        self.client.post(f"/dishes/{did}/delete")
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertIsNone(conn.execute("SELECT * FROM custom_dishes").fetchone())

    def test_recent_mains(self):
        self.client.post("/draw", data={"mode": "single", "style": ""})
        with app_module.app.app_context():
            conn = app_module.get_db()
            recent = app_module.recent_mains(conn, 3)
            saved = conn.execute("SELECT main_name FROM history").fetchone()["main_name"]
        self.assertIn(saved, recent)


if __name__ == "__main__":
    unittest.main()
