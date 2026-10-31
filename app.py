"""献立ルーレット menuroulette

内蔵の献立リスト（主菜・副菜・汁物／和・洋・中）から、1品または
3品セットをランダムに抽選する汎用ツール。自作の献立の追加もできる。
抽選履歴は SQLite に JST 時刻つきで保存する。
単一ファイル Flask + SQLite。
"""
import os
import random
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("MENUROULETTE_DB", os.path.join(os.path.dirname(__file__), "menuroulette.db"))

# (名前, 区分, 系統)
BUILTIN = [
    # 主菜・和
    ("肉じゃが", "主菜", "和"), ("鯖の味噌煮", "主菜", "和"), ("鶏の照り焼き", "主菜", "和"),
    ("豚の生姜焼き", "主菜", "和"), ("親子丼", "主菜", "和"), ("鮭の塩焼き", "主菜", "和"),
    ("鶏の唐揚げ", "主菜", "和"), ("すき焼き風煮物", "主菜", "和"), ("ぶりの照り焼き", "主菜", "和"),
    ("とんかつ", "主菜", "和"),
    # 主菜・洋
    ("ハンバーグ", "主菜", "洋"), ("チキンソテー", "主菜", "洋"), ("ポークチャップ", "主菜", "洋"),
    ("オムライス", "主菜", "洋"), ("クリームシチュー", "主菜", "洋"), ("グラタン", "主菜", "洋"),
    ("鮭のムニエル", "主菜", "洋"),
    # 主菜・中
    ("麻婆豆腐", "主菜", "中"), ("回鍋肉", "主菜", "中"), ("青椒肉絲", "主菜", "中"),
    ("酢豚", "主菜", "中"), ("餃子", "主菜", "中"), ("エビチリ", "主菜", "中"), ("八宝菜", "主菜", "中"),
    # 副菜・和
    ("ほうれん草のおひたし", "副菜", "和"), ("きんぴらごぼう", "副菜", "和"),
    ("ひじきの煮物", "副菜", "和"), ("だし巻き卵", "副菜", "和"), ("ポテトサラダ", "副菜", "和"),
    ("切り干し大根の煮物", "副菜", "和"), ("なます", "副菜", "和"),
    # 副菜・洋
    ("コールスロー", "副菜", "洋"), ("キャロットラペ", "副菜", "洋"),
    ("マカロニサラダ", "副菜", "洋"), ("ほうれん草のソテー", "副菜", "洋"), ("温野菜サラダ", "副菜", "洋"),
    # 副菜・中
    ("もやしナムル", "副菜", "中"), ("中華風春雨サラダ", "副菜", "中"),
    ("ザーサイ豆腐", "副菜", "中"), ("きゅうりの中華和え", "副菜", "中"),
    # 汁物
    ("味噌汁（豆腐とわかめ）", "汁物", "和"), ("味噌汁（なす）", "汁物", "和"),
    ("豚汁", "汁物", "和"), ("けんちん汁", "汁物", "和"), ("すまし汁", "汁物", "和"),
    ("コンソメスープ", "汁物", "洋"), ("コーンスープ", "汁物", "洋"),
    ("わかめスープ", "汁物", "中"), ("卵スープ", "汁物", "中"),
]

CATEGORIES = ["主菜", "副菜", "汁物"]
STYLES = ["和", "洋", "中"]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS custom_dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            style TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            main_name TEXT NOT NULL DEFAULT '',
            side_name TEXT NOT NULL DEFAULT '',
            soup_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def all_dishes(db):
    dishes = list(BUILTIN)
    for row in db.execute("SELECT name, category, style FROM custom_dishes"):
        dishes.append((row["name"], row["category"], row["style"]))
    return dishes


def recent_mains(db, n=3):
    rows = db.execute(
        "SELECT main_name FROM history WHERE main_name != '' ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    return {r["main_name"] for r in rows}


def pick(db, category, style, avoid=frozenset()):
    pool = [
        name for (name, cat, sty) in all_dishes(db)
        if cat == category and (style is None or sty == style) and name not in avoid
    ]
    if not pool:
        return None
    return random.choice(pool)


def draw_set(db, style, avoid_recent):
    avoid = recent_mains(db, 3) if avoid_recent else frozenset()
    main = pick(db, "主菜", style, avoid)
    if main is None and avoid:
        main = pick(db, "主菜", style)  # 避けると候補が尽きる場合は通常抽選
    return main, pick(db, "副菜", style), pick(db, "汁物", style)


PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>献立ルーレット</title>
<style>body{font-family:sans-serif;max-width:680px;margin:2em auto;padding:0 1em}
.result{background:#fdf6e3;border:1px solid #d9b84a;padding:1em;border-radius:8px;font-size:1.15em}
table{border-collapse:collapse}td,th{border-bottom:1px solid #ccc;padding:.3em .6em}</style>
</head><body>
<h1>献立ルーレット</h1>
<p>今日の献立をランダムに決めます（内蔵 {{ builtin_count }} 品＋自作 {{ custom_count }} 品）。</p>
<form method="post" action="{{ url_for('draw') }}">
  <label>モード
    <select name="mode"><option value="set">3品セット（主菜＋副菜＋汁物）</option><option value="single">主菜だけ1品</option></select></label>
  <label>系統
    <select name="style"><option value="">指定なし</option>{% for s in styles %}<option>{{ s }}</option>{% endfor %}</select></label>
  <label><input type="checkbox" name="avoid_recent" value="1" checked> 直近3回の主菜を避ける</label>
  <button type="submit">抽選する</button>
</form>

{% if result %}
<div class="result">
  {% if result.main %}<div>主菜：<strong>{{ result.main }}</strong></div>{% endif %}
  {% if result.side %}<div>副菜：<strong>{{ result.side }}</strong></div>{% endif %}
  {% if result.soup %}<div>汁物：<strong>{{ result.soup }}</strong></div>{% endif %}
  {% if not result.main and not result.side and not result.soup %}<div>候補がありませんでした。条件をゆるめてください。</div>{% endif %}
</div>
{% endif %}

<h2>自作の献立を追加</h2>
<form method="post" action="{{ url_for('add_dish') }}">
  <input type="text" name="name" placeholder="料理名" required>
  <select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select>
  <select name="style">{% for s in styles %}<option>{{ s }}</option>{% endfor %}</select>
  <button type="submit">追加</button>
</form>
<ul>
{% for d in customs %}
<li>{{ d.name }}（{{ d.category }}／{{ d.style }}）
  <form method="post" action="{{ url_for('delete_dish', did=d.id) }}" style="display:inline"><button>削除</button></form></li>
{% else %}<li>自作の献立はまだありません</li>{% endfor %}
</ul>

<h2>抽選履歴</h2>
{% if history %}
<form method="post" action="{{ url_for('clear_history') }}" onsubmit="return confirm('抽選履歴を全て削除しますか？')"><button type="submit">履歴を全て削除</button></form>
{% endif %}
<table>
<tr><th>日時</th><th>主菜</th><th>副菜</th><th>汁物</th><th>操作</th></tr>
{% for h in history %}
<tr><td>{{ h.created_at }}</td><td>{{ h.main_name }}</td><td>{{ h.side_name }}</td><td>{{ h.soup_name }}</td><td><form method="post" action="{{ url_for('delete_history', hid=h.id) }}" style="display:inline" onsubmit="return confirm('この履歴を削除しますか？')"><button type="submit">削除</button></form></td></tr>
{% else %}<tr><td colspan="5">履歴はまだありません</td></tr>
{% endfor %}
</table>
</body></html>"""


def render_page(result=None):
    db = get_db()
    customs = db.execute("SELECT * FROM custom_dishes ORDER BY id DESC").fetchall()
    history = db.execute("SELECT * FROM history ORDER BY id DESC LIMIT 30").fetchall()
    return render_template_string(
        PAGE, result=result, customs=customs, history=history,
        builtin_count=len(BUILTIN), custom_count=len(customs),
        categories=CATEGORIES, styles=STYLES,
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return render_page()


@app.route("/draw", methods=["POST"])
def draw():
    db = get_db()
    mode = request.form.get("mode", "set")
    style = request.form.get("style") or None
    if style not in STYLES:
        style = None
    avoid_recent = request.form.get("avoid_recent") == "1"
    if mode == "single":
        avoid = recent_mains(db, 3) if avoid_recent else frozenset()
        main = pick(db, "主菜", style, avoid)
        if main is None and avoid:
            main = pick(db, "主菜", style)
        result = {"main": main, "side": None, "soup": None}
    else:
        main, side, soup = draw_set(db, style, avoid_recent)
        result = {"main": main, "side": side, "soup": soup}
    if result["main"] or result["side"] or result["soup"]:
        db.execute(
            "INSERT INTO history(main_name, side_name, soup_name, created_at) VALUES(?, ?, ?, ?)",
            (result["main"] or "", result["side"] or "", result["soup"] or "",
             datetime.now(JST).strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
    return render_page(result=result)


@app.route("/dishes", methods=["POST"])
def add_dish():
    name = (request.form.get("name") or "").strip()
    category = request.form.get("category", "主菜")
    style = request.form.get("style", "和")
    if name and category in CATEGORIES and style in STYLES:
        db = get_db()
        db.execute(
            "INSERT INTO custom_dishes(name, category, style) VALUES(?, ?, ?)",
            (name, category, style),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/history/<int:hid>/delete", methods=["POST"])
def delete_history(hid):
    db = get_db()
    db.execute("DELETE FROM history WHERE id = ?", (hid,))
    db.commit()
    return redirect(url_for("index"))


@app.route("/history/clear", methods=["POST"])
def clear_history():
    db = get_db()
    db.execute("DELETE FROM history")
    db.commit()
    return redirect(url_for("index"))


@app.route("/dishes/<int:did>/delete", methods=["POST"])
def delete_dish(did):
    db = get_db()
    db.execute("DELETE FROM custom_dishes WHERE id = ?", (did,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
