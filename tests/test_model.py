"""警報コードの解釈と震度の並びのテスト。ここが狂うと色分けと順序が全部ずれる。"""
from datetime import datetime

from bosai.model import (ADVISORY, EMERGENCY, JST, PREFECTURES, WARNING, PrefWarning, WarningItem, intensity_class,
                         intensity_label, intensity_rank, is_active, parse_coordinate, parse_dt, pref_of_office,
                         sort_warning_codes, warning_level, warning_name, weather_from_code, weather_icon)


def test_都道府県は47個ありスラッグが重複しない():
    assert len(PREFECTURES) == 47
    slugs = [s for _, s in PREFECTURES.values()]
    assert len(set(slugs)) == 47


def test_気象台コードから都道府県が出る():
    assert pref_of_office("130000") == "13"      # 東京都
    assert pref_of_office("011000") == "01"      # 宗谷地方（北海道）
    assert pref_of_office("014030") == "01"      # 十勝地方（北海道）
    assert pref_of_office("460040") == "46"      # 奄美地方（鹿児島県）
    assert pref_of_office("474000") == "47"      # 八重山地方（沖縄県）


def test_警報コードの段階():
    assert warning_level("33") == EMERGENCY and warning_name("33") == "大雨特別警報"
    assert warning_level("03") == WARNING and warning_name("03") == "大雨警報"
    assert warning_level("10") == ADVISORY and warning_name("10") == "大雨注意報"
    # 実際に気象庁から返ってきたことのあるコード
    assert warning_name("14") == "雷注意報"
    assert warning_name("15") == "強風注意報"
    assert warning_name("16") == "波浪注意報"
    assert warning_name("20") == "濃霧注意報"
    assert warning_name("21") == "乾燥注意報"


def test_知らないコードでも壊れない():
    assert warning_level("99") == ADVISORY
    assert "99" in warning_name("99")


def test_並べ替えは特別警報から注意報の順():
    assert sort_warning_codes(["14", "03", "33", "10", "03"]) == ["33", "03", "10", "14"]


def test_解除は出ている扱いにしない():
    assert is_active("発表") and is_active("継続")
    assert not is_active("解除")
    assert not is_active("発表警報・注意報はなし")
    assert not is_active(None)


def test_震度の並び():
    order = ["1", "2", "3", "4", "5-", "5+", "6-", "6+", "7"]
    ranks = [intensity_rank(v) for v in order]
    assert ranks == sorted(ranks)
    assert intensity_rank("5+") > intensity_rank("5-")
    assert intensity_rank("6-") > intensity_rank("5+")
    assert intensity_rank("") == -1
    assert intensity_rank(None) == -1


def test_震度の表示():
    assert intensity_label("5-") == "震度5弱"
    assert intensity_label("6+") == "震度6強"
    assert intensity_label("3") == "震度3"
    assert intensity_label("") == "震度なし"
    assert intensity_class("") == "i-none"
    assert intensity_class("7") != intensity_class("1")


def test_地震を最大震度で並べ替えられる():
    values = ["3", "5+", "1", "5-", "7", "", "6-"]
    assert sorted(values, key=intensity_rank, reverse=True) == ["7", "6-", "5+", "5-", "3", "1", ""]


def test_日時を読む():
    d = parse_dt("2026-09-21T21:14:00+09:00")
    assert (d.year, d.month, d.day, d.hour) == (2026, 9, 21, 21)
    assert parse_dt("20260921211445").tzinfo == JST
    assert parse_dt(None) is None
    assert parse_dt("こわれた") is None


def test_震源の座標を読む():
    assert parse_coordinate("+32.2+130.4-10000/") == (32.2, 130.4, 10.0)
    assert parse_coordinate("-06.1+105.4/") == (-6.1, 105.4, None)
    assert parse_coordinate("+38.2+142.0-60000/") == (38.2, 142.0, 60.0)
    assert parse_coordinate(None) == (None, None, None)


def test_天気の絵文字():
    assert weather_icon("雨　夜遅く　くもり") == "☔"
    assert weather_icon("くもり　時々　晴れ") == "☁"
    assert weather_icon("晴れ") == "☀"
    assert weather_icon(None, "201") == "☁"
    assert weather_from_code("313") == "雨"
    assert weather_from_code(None) == "―"


def test_都道府県の状態():
    p = PrefWarning("13", datetime(2026, 9, 21, tzinfo=JST), [], [WarningItem("03", ["東京地方"]), WarningItem("14", ["島"])])
    assert p.name == "東京都" and p.slug == "tokyo" and p.path == "area/tokyo/"
    assert p.top_level == WARNING and p.has_warning
    assert [w.code for w in p.warnings] == ["03"]
    assert [w.code for w in p.advisories] == ["14"]

    quiet = PrefWarning("13", None, [], [])
    assert quiet.top_level is None and not quiet.has_warning
    assert quiet.summary == "発表中の警報・注意報はありません"

    only_adv = PrefWarning("13", None, [], [WarningItem("14", ["東京地方"])])
    assert only_adv.top_level == ADVISORY and not only_adv.has_warning

    special = PrefWarning("13", None, [], [WarningItem("33", ["東京地方"]), WarningItem("03", ["島"])])
    assert special.top_level == EMERGENCY and special.has_warning
