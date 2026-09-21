"""気象庁の生 JSON を、こちらの形に潰すところのテスト（ネットワークは使わない）。"""
from bosai.jma import condense_forecast, condense_quake, condense_warning

AREA_NAMES = {"130010": "東京地方", "130020": "伊豆諸島北部", "130030": "伊豆諸島南部"}

RAW_WARNING = {
    "reportDatetime": "2026-05-28T10:16:00+09:00",
    "publishingOffice": "気象庁",
    "headlineText": "伊豆諸島南部では、強風や高波に注意してください。",
    "areaTypes": [
        {"areas": [
            {"code": "130010", "warnings": [{"status": "発表警報・注意報はなし"}]},
            {"code": "130020", "warnings": [{"code": "14", "status": "継続"}, {"code": "20", "status": "解除"}]},
            {"code": "130030", "warnings": [{"code": "03", "status": "発表"}, {"code": "14", "status": "発表"}]},
        ]},
        {"areas": [{"code": "1310100", "warnings": [{"code": "14", "status": "発表"}]}]},
    ],
}


def test_警報は出ている分だけを一次細分区域でまとめる():
    row = condense_warning(RAW_WARNING, "130000", "東京都", AREA_NAMES)
    assert row["pref"] == "13"
    assert row["office_name"] == "東京都"
    assert row["headline"].startswith("伊豆諸島南部")
    # 大雨警報が先、雷注意報が後。解除された濃霧注意報は入らない
    assert [w["code"] for w in row["warnings"]] == ["03", "14"]
    assert row["warnings"][0]["areas"] == ["伊豆諸島南部"]
    assert row["warnings"][1]["areas"] == ["伊豆諸島北部", "伊豆諸島南部"]


def test_警報が何も出ていなければ空になる():
    raw = {"reportDatetime": "2026-05-28T10:16:00+09:00", "areaTypes":
           [{"areas": [{"code": "130010", "warnings": [{"status": "発表警報・注意報はなし"}]}]}]}
    row = condense_warning(raw, "130000", "東京都", AREA_NAMES)
    assert row["warnings"] == [] and row["headline"] == ""


RAW_FORECAST = [
    {"publishingOffice": "気象庁", "reportDatetime": "2026-09-21T17:00:00+09:00", "timeSeries": [
        {"timeDefines": ["2026-09-21T17:00:00+09:00", "2026-09-22T00:00:00+09:00"],
         "areas": [{"area": {"name": "東京地方", "code": "130010"},
                    "weatherCodes": ["313", "201"], "weathers": ["雨　後　くもり", "くもり　時々　晴れ"],
                    "winds": ["北の風", "東の風"], "waves": ["２．５メートル", "０．５メートル"]}]},
        {"timeDefines": ["2026-09-21T18:00:00+09:00", "2026-09-22T00:00:00+09:00", "2026-09-22T06:00:00+09:00"],
         "areas": [{"area": {"name": "東京地方", "code": "130010"}, "pops": ["80", "20", "0"]}]},
        {"timeDefines": ["2026-09-22T00:00:00+09:00", "2026-09-22T09:00:00+09:00"],
         "areas": [{"area": {"name": "東京", "code": "44132"}, "temps": ["25", "29"]}]},
    ]},
    {"reportDatetime": "2026-09-21T17:00:00+09:00", "timeSeries": [
        {"timeDefines": ["2026-09-22T00:00:00+09:00", "2026-09-23T00:00:00+09:00"],
         "areas": [{"area": {"name": "東京地方", "code": "130010"}, "weatherCodes": ["201", "200"], "pops": ["", "40"]}]},
        {"timeDefines": ["2026-09-22T00:00:00+09:00", "2026-09-23T00:00:00+09:00"],
         "areas": [{"area": {"name": "東京", "code": "44132"}, "tempsMin": ["", "20"], "tempsMax": ["", "27"]}]},
    ]},
]


def test_予報は日付ごとの行に組み直される():
    row = condense_forecast(RAW_FORECAST, "130000", "東京都")
    area = row["areas"][0]
    assert area["name"] == "東京地方"
    assert area["days"][0]["date"] == "2026-09-21"
    assert area["days"][0]["weather"].startswith("雨")
    # 降水確率は日付でまとめ、その日の最大も持つ
    assert [r["pop"] for r in area["days"][0]["pops"]] == ["80"]
    assert area["days"][0]["pop_max"] == 80
    assert [r["pop"] for r in area["days"][1]["pops"]] == ["20", "0"]
    assert area["days"][1]["pop_max"] == 20
    assert row["temps"][0]["name"] == "東京"
    assert row["weekly"][0]["rows"][1]["code"] == "200"
    assert row["weekly_temps"][0]["rows"][1] == {"date": "2026-09-23", "min": "20", "max": "27"}


def test_予報が空でも落ちない():
    row = condense_forecast([], "130000", "東京都")
    assert row["areas"] == [] and row["weekly"] == []


QUAKE_ROW = {"eid": "20260916060939", "ctt": "20260916061350", "rdt": "2026-09-16T06:13:00+09:00",
             "ttl": "震源・震度情報", "at": "2026-09-16T06:09:00+09:00", "anm": "熊本県天草・芦北地方",
             "cod": "+32.2+130.4-10000/", "mag": "4.0", "maxi": "4", "json": "x.json"}
QUAKE_DETAIL = {"Body": {
    "Earthquake": {"OriginTime": "2026-09-16T06:09:00+09:00",
                   "Hypocenter": {"Area": {"Name": "熊本県天草・芦北地方", "Coordinate": "+32.2+130.4-10000/"}},
                   "Magnitude": "4.0"},
    "Intensity": {"Observation": {"MaxInt": "4", "Pref": [
        {"Name": "熊本県", "MaxInt": "4", "Area": [
            {"Name": "熊本県天草・芦北", "MaxInt": "4",
             "City": [{"Name": "水俣市", "MaxInt": "4"}, {"Name": "芦北町", "MaxInt": "3"}]}]}]}},
    "Comments": {"ForecastComment": {"Text": "この地震による津波の心配はありません。"}}}}


def test_地震はページに要るものだけ残す():
    row = condense_quake(QUAKE_ROW, QUAKE_DETAIL)
    assert row["id"] == "20260916060939"
    assert row["place"] == "熊本県天草・芦北地方"
    assert (row["lat"], row["lon"], row["depth"]) == (32.2, 130.4, 10.0)
    assert row["max_int"] == "4"
    assert row["prefs"][0]["cities"] == [["水俣市", "4"], ["芦北町", "3"]]
    assert "津波の心配はありません" in row["comment"]


def test_震度速報は区域までしか無くても読める():
    row_in = dict(QUAKE_ROW, ttl="震度速報", maxi="3", cod=None)
    detail = {"Body": {"Intensity": {"Observation": {"MaxInt": "3", "Pref": [
        {"Name": "鹿児島県", "MaxInt": "3", "Area": [{"Name": "鹿児島県奄美北部", "MaxInt": "3"}]}]}}}}
    row = condense_quake(row_in, detail)
    assert row["prefs"][0]["cities"] == [["鹿児島県奄美北部", "3"]]
    assert row["place"] == "熊本県天草・芦北地方"  # 震源が無ければ一覧の地名を使う
    assert row["lat"] is None


def test_詳細が取れなくても一覧の分だけで作れる():
    row = condense_quake(QUAKE_ROW, None)
    assert row["place"] == "熊本県天草・芦北地方"
    assert row["magnitude"] == "4.0"
    assert row["prefs"] == [] and row["comment"] == ""
