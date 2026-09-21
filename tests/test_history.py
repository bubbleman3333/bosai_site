"""観測記録（data/history/）の足し込みと集計のテスト。"""
import json
from datetime import datetime, timedelta

from bosai.history import load_days, record_day, tally
from bosai.model import JST

DAY = datetime(2026, 9, 21, 10, 0, tzinfo=JST)


def rows(pref_codes):
    """{都道府県コード: [警報コード]} を、取り込み結果の形に直す。"""
    return [{"pref": p, "warnings": [{"code": c, "areas": ["どこか"]} for c in codes]}
            for p, codes in pref_codes.items()]


def test_同じ日に何度書いても和集合になる(tmp_path):
    record_day(rows({"13": ["14"]}), tmp_path, DAY)
    record_day(rows({"13": ["14", "03"], "27": []}), tmp_path, DAY + timedelta(hours=1))
    data = json.loads((tmp_path / "2026-09-21.json").read_text(encoding="utf-8"))
    assert data["observations"] == 2
    assert data["prefs"]["13"]["warning"] == ["03"]
    assert data["prefs"]["13"]["advisory"] == ["14"]
    assert data["prefs"]["13"]["emergency"] == []
    assert data["prefs"]["27"] == {"emergency": [], "warning": [], "advisory": []}


def test_日をまたぐと別のファイルになる(tmp_path):
    record_day(rows({"13": ["03"]}), tmp_path, DAY)
    record_day(rows({"13": ["14"]}), tmp_path, DAY + timedelta(days=1))
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-09-21.json", "2026-09-22.json"]
    assert len(load_days(tmp_path)) == 2


def test_ランキングは警報が出た日数の多い順(tmp_path):
    record_day(rows({"13": ["03"], "27": ["14"], "01": ["33"]}), tmp_path, DAY)
    record_day(rows({"13": ["03"], "27": ["14"]}), tmp_path, DAY + timedelta(days=1))
    record_day(rows({"27": ["03"]}), tmp_path, DAY + timedelta(days=2))
    stats = tally(load_days(tmp_path))
    assert stats["days"] == 3 and stats["first"] == "2026-09-21" and stats["last"] == "2026-09-23"
    names = [r["name"] for r in stats["ranking"]]
    # 東京 2 日・大阪 1 日・北海道 1 日（特別警報も警報として数える）
    assert names[0] == "東京都"
    by_name = {r["name"]: r for r in stats["ranking"]}
    assert by_name["東京都"]["warning_days"] == 2
    assert by_name["大阪府"]["warning_days"] == 1 and by_name["大阪府"]["advisory_days"] == 2
    assert by_name["北海道"]["warning_days"] == 1
    assert dict(stats["code_days"])["03"] == 3
    assert dict(stats["code_days"])["33"] == 1


def test_記録が無くても集計できる(tmp_path):
    stats = tally(load_days(tmp_path))
    assert stats == {"days": 0, "first": None, "last": None, "ranking": [], "code_days": []}


def test_壊れたファイルは飛ばす(tmp_path):
    (tmp_path / "2026-09-21.json").write_text("{ここが壊れている", encoding="utf-8")
    record_day(rows({"13": ["03"]}), tmp_path, DAY)
    assert len(load_days(tmp_path)) == 1
