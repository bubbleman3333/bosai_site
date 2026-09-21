"""ビルドが一式のファイルを出すことのテスト。

テンプレート・CSS・固定ページは本物を使い、data/ だけを差し替える。
"""
import json
from datetime import datetime

import pytest

from bosai.build import ROOT, Builder, fmt_day
from bosai.model import JST

NOW = datetime(2026, 9, 21, 22, 0, tzinfo=JST)
SITE_URL = "https://example.test/bosai_site"


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    # 東京: 大雨警報 + 雷注意報 / 大阪: 注意報だけ / 北海道は 2 つの気象台に分かれる
    write(d / "current" / "warning" / "130000.json", {
        "office": "130000", "office_name": "東京都", "pref": "13", "report": "2026-09-21T10:16:00+09:00",
        "headline": "東京地方では、土砂災害に警戒してください。",
        "warnings": [{"code": "03", "areas": ["東京地方"]}, {"code": "14", "areas": ["東京地方", "伊豆諸島北部"]}]})
    write(d / "current" / "warning" / "270000.json", {
        "office": "270000", "office_name": "大阪府", "pref": "27", "report": "2026-09-21T09:00:00+09:00",
        "headline": "", "warnings": [{"code": "20", "areas": ["大阪府"]}]})
    write(d / "current" / "warning" / "016000.json", {
        "office": "016000", "office_name": "石狩・空知・後志地方", "pref": "01",
        "report": "2026-09-21T09:00:00+09:00", "headline": "", "warnings": [{"code": "15", "areas": ["石狩地方"]}]})
    write(d / "current" / "warning" / "017000.json", {
        "office": "017000", "office_name": "渡島・檜山地方", "pref": "01",
        "report": "2026-09-21T11:00:00+09:00", "headline": "", "warnings": [{"code": "15", "areas": ["渡島地方"]}]})
    write(d / "current" / "forecast" / "130000.json", {
        "office": "130000", "office_name": "東京都", "pref": "13", "report": "2026-09-21T17:00:00+09:00",
        "areas": [{"code": "130010", "name": "東京地方", "days": [
            {"date": "2026-09-21", "weather": "雨", "code": "313", "wind": "北の風", "wave": "２．５メートル",
             "pops": [{"date": "2026-09-21", "hour": "18", "pop": "80"}], "pop_max": 80},
            {"date": "2026-09-22", "weather": "くもり", "code": "201", "wind": "東の風", "wave": "",
             "pops": [], "pop_max": None}]}],
        "temps": [{"name": "東京", "rows": [{"date": "2026-09-22", "hour": "00", "temp": "25"}]}],
        "weekly": [{"name": "東京地方", "rows": [{"date": "2026-09-23", "code": "200", "pop": "40"}]}],
        "weekly_temps": [{"name": "東京", "rows": [{"date": "2026-09-23", "min": "20", "max": "27"}]}]})
    write(d / "quakes" / "20260916060939.json", {
        "id": "20260916060939", "ctt": "20260916061350", "report": "2026-09-16T06:13:00+09:00",
        "origin": "2026-09-16T06:09:00+09:00", "kind": "震源・震度情報", "place": "熊本県天草・芦北地方",
        "magnitude": "4.0", "lat": 32.2, "lon": 130.4, "depth": 10.0, "max_int": "4",
        # 気象庁の並びは震度順ではない（読み込むときに強い順へ直す）
        "prefs": [{"name": "鹿児島県", "max_int": "3", "cities": [["阿久根市", "1"], ["出水市", "3"]]},
                  {"name": "熊本県", "max_int": "4", "cities": [["芦北町", "3"], ["水俣市", "4"]]}],
        "comment": "この地震による津波の心配はありません。"})
    write(d / "quakes" / "20260921211445.json", {
        "id": "20260921211445", "ctt": "20260921211738", "report": "2026-09-21T21:17:00+09:00",
        "origin": "2026-09-21T21:14:00+09:00", "kind": "震源・震度情報", "place": "宮城県沖",
        "magnitude": "3.6", "lat": 38.2, "lon": 142.0, "depth": 60.0, "max_int": "1",
        "prefs": [{"name": "宮城県", "max_int": "1", "cities": [["石巻市", "1"]]}], "comment": ""})
    # 震源も震度も無い形（遠地地震）
    write(d / "quakes" / "20260905025000.json", {
        "id": "20260905025000", "ctt": "20260905030000", "report": "2026-09-05T03:00:00+09:00",
        "origin": "2026-09-05T02:50:00+09:00", "kind": "遠地地震に関する情報", "place": "インドネシア付近",
        "magnitude": "Ｍ不明", "lat": -6.1, "lon": 105.4, "depth": None, "max_int": "",
        "prefs": [], "comment": "この地震による日本への津波の影響はありません。"})
    write(d / "history" / "2026-09-20.json", {
        "date": "2026-09-20", "updated": "2026-09-20T23:00:00+09:00", "observations": 24,
        "prefs": {"13": {"emergency": [], "warning": ["03"], "advisory": ["14"]}}})
    return d


@pytest.fixture
def built(tmp_path, data_dir):
    out = tmp_path / "dist"
    pages = Builder(out, SITE_URL, now=NOW, data_dir=data_dir, root=ROOT).build()
    return out, pages


def test_一式のファイルが出る(built):
    out, pages = built
    must = [
        "index.html", "404.html", "robots.txt", "sitemap.xml", "feed.xml", ".nojekyll",
        "static/style.css", "static/favicon.svg", "static/og.png",
        "about/index.html", "privacy/index.html",
        "area/index.html", "ranking/index.html",
        "quake/index.html", "quake/strong/index.html", "quake/strong/2026-09/index.html",
        "quake/20260916060939/index.html", "quake/20260921211445/index.html",
        "quake/20260905025000/index.html",
    ]
    for name in must:
        assert (out / name).exists(), f"{name} が無い"
    # 47 都道府県ぶんのページ
    areas = [p for p in (out / "area").iterdir() if p.is_dir()]
    assert len(areas) == 47
    assert (out / "area" / "tokyo" / "index.html").exists()
    assert (out / "area" / "okinawa" / "index.html").exists()
    assert pages > 47


def test_テンプレートの取り違えが無い(built):
    """Jinja2 で辞書の pop などメソッドを引いてしまうと '<built-in method ...>' が出る。"""
    out, _ = built
    for path in out.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "built-in method" not in text, f"{path} にメソッドがそのまま出ている"
        assert "object at 0x" not in text, f"{path} にオブジェクトがそのまま出ている"


def test_トップに警報の県と地震が出る(built):
    out, _ = built
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "大雨警報" in html            # 東京に警報
    assert "東京都" in html
    assert "熊本県天草・芦北地方" in html  # 最近の地震
    assert "気象庁" in html               # 出典


def test_北海道は複数の気象台がひとつにまとまる(built):
    out, _ = built
    html = (out / "area" / "hokkaido" / "index.html").read_text(encoding="utf-8")
    assert "強風注意報" in html
    assert "石狩地方" in html and "渡島地方" in html


def test_都道府県ページに天気と地震が出る(built):
    out, _ = built
    html = (out / "area" / "tokyo" / "index.html").read_text(encoding="utf-8")
    assert "大雨警報" in html and "雷注意報" in html
    assert "土砂災害に警戒" in html
    assert "降水確率" in html and "80%" in html
    assert "9月22日(火)" in html
    assert 'href="' + SITE_URL + '/' in html


def test_警報が出ていない県はその旨が出る(built):
    out, _ = built
    html = (out / "area" / "aomori" / "index.html").read_text(encoding="utf-8")
    assert "発表中の警報・注意報はありません" in html


def test_地震ページに各地の震度が出る(built):
    out, _ = built
    html = (out / "quake" / "20260916060939" / "index.html").read_text(encoding="utf-8")
    assert "震度4" in html and "水俣市" in html
    assert "M4.0" in html and "約10km" in html
    assert "津波の心配はありません" in html
    # 都道府県も市区町村も震度の強い順に並ぶ
    assert html.index("熊本県") < html.index("鹿児島県")
    assert html.index("水俣市") < html.index("芦北町")
    assert html.index("出水市") < html.index("阿久根市")


def test_震度も震源も欠けた地震でも作れる(built):
    out, _ = built
    html = (out / "quake" / "20260905025000" / "index.html").read_text(encoding="utf-8")
    assert "インドネシア付近" in html
    assert "不明" in html


def test_震度4以上のまとめは今月分だけを拾う(built):
    out, _ = built
    html = (out / "quake" / "strong" / "2026-09" / "index.html").read_text(encoding="utf-8")
    main = html.split("<aside")[0]  # 右側のサイドバーには最近の地震が出るので本文だけを見る
    assert "熊本県天草・芦北地方" in main
    assert "宮城県沖" not in main  # 震度 1 なので入らない


def test_ランキングは観測記録から作る(built):
    out, _ = built
    html = (out / "ranking" / "index.html").read_text(encoding="utf-8")
    assert "東京都" in html and "大雨警報" in html
    assert "公式統計ではありません" in html


def test_サイトマップとRSSと構造化データ(built):
    out, _ = built
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<url>") > 47
    assert f"{SITE_URL}/area/tokyo/" in sitemap
    feed = (out / "feed.xml").read_text(encoding="utf-8")
    assert "【警報】東京都に大雨警報" in feed
    assert "宮城県沖" not in feed  # 震度 1 は RSS に出さない
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '"@type":"WebSite"' in index
    tokyo = (out / "area" / "tokyo" / "index.html").read_text(encoding="utf-8")
    assert '"@type":"BreadcrumbList"' in tokyo
    assert '"@type":"CollectionPage"' in tokyo
    assert f'<link rel="canonical" href="{SITE_URL}/area/tokyo/">' in tokyo
    assert 'property="og:image"' in tokyo
    robots = (out / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {SITE_URL}/sitemap.xml" in robots


def test_404は検索避けにする(built):
    out, _ = built
    html = (out / "404.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex"' in html
    assert f"{SITE_URL}/404.html" not in (out / "sitemap.xml").read_text(encoding="utf-8")


def test_データが空でもビルドできる(tmp_path):
    out = tmp_path / "dist"
    pages = Builder(out, SITE_URL, now=NOW, data_dir=tmp_path / "からっぽ", root=ROOT).build()
    assert pages > 47
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "いま警報が出ている都道府県はありません" in html


def test_日付の表示():
    assert fmt_day("2026-09-21") == "9月21日(月)"
    assert fmt_day("2026-09-22") == "9月22日(火)"
    assert fmt_day(None) == ""
