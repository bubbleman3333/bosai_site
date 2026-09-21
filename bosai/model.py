"""気象庁の生データを、テンプレートから扱いやすい形に直す。

ここには「意味の対応表」（警報コード、震度、都道府県）と、それを使う小さなデータ構造だけを置く。
ネットワークには触らない（取り込みは jma.py）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------- 都道府県
# 気象庁の「気象台（office）」コードは先頭 2 桁が都道府県の JIS コードになっている。
# 例: 130000=東京都、011000=宗谷地方（北海道）、460040=奄美地方（鹿児島県）。
PREFECTURES: dict[str, tuple[str, str]] = {
    "01": ("北海道", "hokkaido"), "02": ("青森県", "aomori"), "03": ("岩手県", "iwate"),
    "04": ("宮城県", "miyagi"), "05": ("秋田県", "akita"), "06": ("山形県", "yamagata"),
    "07": ("福島県", "fukushima"), "08": ("茨城県", "ibaraki"), "09": ("栃木県", "tochigi"),
    "10": ("群馬県", "gunma"), "11": ("埼玉県", "saitama"), "12": ("千葉県", "chiba"),
    "13": ("東京都", "tokyo"), "14": ("神奈川県", "kanagawa"), "15": ("新潟県", "niigata"),
    "16": ("富山県", "toyama"), "17": ("石川県", "ishikawa"), "18": ("福井県", "fukui"),
    "19": ("山梨県", "yamanashi"), "20": ("長野県", "nagano"), "21": ("岐阜県", "gifu"),
    "22": ("静岡県", "shizuoka"), "23": ("愛知県", "aichi"), "24": ("三重県", "mie"),
    "25": ("滋賀県", "shiga"), "26": ("京都府", "kyoto"), "27": ("大阪府", "osaka"),
    "28": ("兵庫県", "hyogo"), "29": ("奈良県", "nara"), "30": ("和歌山県", "wakayama"),
    "31": ("鳥取県", "tottori"), "32": ("島根県", "shimane"), "33": ("岡山県", "okayama"),
    "34": ("広島県", "hiroshima"), "35": ("山口県", "yamaguchi"), "36": ("徳島県", "tokushima"),
    "37": ("香川県", "kagawa"), "38": ("愛媛県", "ehime"), "39": ("高知県", "kochi"),
    "40": ("福岡県", "fukuoka"), "41": ("佐賀県", "saga"), "42": ("長崎県", "nagasaki"),
    "43": ("熊本県", "kumamoto"), "44": ("大分県", "oita"), "45": ("宮崎県", "miyazaki"),
    "46": ("鹿児島県", "kagoshima"), "47": ("沖縄県", "okinawa"),
}
PREF_BY_SLUG: dict[str, str] = {slug: code for code, (_, slug) in PREFECTURES.items()}
# 地方のまとまり（トップと都道府県一覧の並べ方）
REGIONS: list[tuple[str, list[str]]] = [
    ("北海道・東北", ["01", "02", "03", "04", "05", "06", "07"]),
    ("関東", ["08", "09", "10", "11", "12", "13", "14"]),
    ("甲信越・北陸", ["15", "16", "17", "18", "19", "20"]),
    ("東海", ["21", "22", "23", "24"]),
    ("近畿", ["25", "26", "27", "28", "29", "30"]),
    ("中国・四国", ["31", "32", "33", "34", "35", "36", "37", "38", "39"]),
    ("九州・沖縄", ["40", "41", "42", "43", "44", "45", "46", "47"]),
]


def pref_of_office(office_code: str) -> str:
    """気象台コード → 都道府県コード（先頭 2 桁）。"""
    return office_code[:2]


def pref_name(code: str) -> str:
    return PREFECTURES.get(code, (code, code))[0]


def pref_slug(code: str) -> str:
    return PREFECTURES.get(code, (code, code))[1]


# ---------------------------------------------------------------- 警報・注意報
# 気象庁は警報コードの対応表を JSON では公開していない（bosai/const/warning_codes.json は 404）。
# そのため「気象警報・注意報」の電文コードをここに持つ。特別警報 > 警報 > 注意報 の 3 段階。
EMERGENCY, WARNING, ADVISORY = "emergency", "warning", "advisory"

WARNING_CODES: dict[str, tuple[str, str]] = {
    # 特別警報
    "32": ("暴風雪特別警報", EMERGENCY),
    "33": ("大雨特別警報", EMERGENCY),
    "35": ("暴風特別警報", EMERGENCY),
    "36": ("大雪特別警報", EMERGENCY),
    "37": ("波浪特別警報", EMERGENCY),
    "38": ("高潮特別警報", EMERGENCY),
    # 警報
    "02": ("暴風雪警報", WARNING),
    "03": ("大雨警報", WARNING),
    "04": ("洪水警報", WARNING),
    "05": ("暴風警報", WARNING),
    "06": ("大雪警報", WARNING),
    "07": ("波浪警報", WARNING),
    "08": ("高潮警報", WARNING),
    # 注意報
    "10": ("大雨注意報", ADVISORY),
    "12": ("大雪注意報", ADVISORY),
    "13": ("風雪注意報", ADVISORY),
    "14": ("雷注意報", ADVISORY),
    "15": ("強風注意報", ADVISORY),
    "16": ("波浪注意報", ADVISORY),
    "17": ("融雪注意報", ADVISORY),
    "18": ("洪水注意報", ADVISORY),
    "19": ("高潮注意報", ADVISORY),
    "20": ("濃霧注意報", ADVISORY),
    "21": ("乾燥注意報", ADVISORY),
    "22": ("なだれ注意報", ADVISORY),
    "23": ("低温注意報", ADVISORY),
    "24": ("霜注意報", ADVISORY),
    "25": ("着氷注意報", ADVISORY),
    "26": ("着雪注意報", ADVISORY),
    "27": ("その他の注意報", ADVISORY),
}

LEVEL_LABEL = {EMERGENCY: "特別警報", WARNING: "警報", ADVISORY: "注意報"}
LEVEL_ORDER = {EMERGENCY: 0, WARNING: 1, ADVISORY: 2}
# 「解除」は出ていたものが取り消された印。出ている扱いにしてはいけない
ACTIVE_STATUS = {"発表", "継続"}


def warning_name(code: str) -> str:
    return WARNING_CODES.get(code, (f"コード{code}の警報・注意報", ADVISORY))[0]


def warning_level(code: str) -> str:
    """特別警報 / 警報 / 注意報 のどれか。知らないコードは注意報扱い（安全側に倒さず控えめに出す）。"""
    return WARNING_CODES.get(code, ("", ADVISORY))[1]


def is_active(status: str | None) -> bool:
    return status in ACTIVE_STATUS


def sort_warning_codes(codes) -> list[str]:
    """特別警報 → 警報 → 注意報 の順、同じ段階ならコード順。"""
    return sorted(set(codes), key=lambda c: (LEVEL_ORDER[warning_level(c)], c))


# ---------------------------------------------------------------- 震度
# 気象庁の震度は 5 と 6 に「弱・強」がある。文字列のままでは並べ替えられないので順番を持つ。
INTENSITY_ORDER: list[str] = ["1", "2", "3", "4", "5-", "5+", "6-", "6+", "7"]
INTENSITY_LABEL: dict[str, str] = {
    "1": "1", "2": "2", "3": "3", "4": "4",
    "5-": "5弱", "5+": "5強", "6-": "6弱", "6+": "6強", "7": "7",
}


def intensity_rank(value: str | None) -> int:
    """震度を並べ替え用の数に直す。震度なし・読めないものは -1。"""
    if not value:
        return -1
    v = value.strip()
    if v in INTENSITY_ORDER:
        return INTENSITY_ORDER.index(v)
    # 「５弱」のような表記でも一応読む
    v = v.replace("５", "5").replace("６", "6").replace("弱", "-").replace("強", "+")
    return INTENSITY_ORDER.index(v) if v in INTENSITY_ORDER else -1


def intensity_label(value: str | None) -> str:
    if not value:
        return "震度なし"
    return "震度" + INTENSITY_LABEL.get(value.strip(), value.strip())


def intensity_class(value: str | None) -> str:
    """CSS の色分け用のクラス名。5 弱以上は目立たせる。"""
    r = intensity_rank(value)
    if r < 0:
        return "i-none"
    return "i" + ("1234"[r] if r < 4 else str(min(r, 8)))


# ---------------------------------------------------------------- 日時・座標
def parse_dt(value: str | None) -> datetime | None:
    """'2026-09-21T21:14:00+09:00' も '20260921211445' も JST の datetime にする。"""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{14}", v):
        return datetime.strptime(v, "%Y%m%d%H%M%S").replace(tzinfo=JST)
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return None


COORD_RE = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)(?:([+-]\d+))?/?")


def parse_coordinate(value: str | None) -> tuple[float | None, float | None, float | None]:
    """'+32.2+130.4-10000/' → (緯度, 経度, 深さ km)。深さが無い形も読む。"""
    if not value:
        return None, None, None
    m = COORD_RE.match(value.strip())
    if not m:
        return None, None, None
    lat, lon = float(m.group(1)), float(m.group(2))
    depth = abs(float(m.group(3))) / 1000 if m.group(3) else None
    return lat, lon, depth


# ---------------------------------------------------------------- 天気
def weather_icon(text: str | None, code: str | None = None) -> str:
    """天気の文字（または天気コード）から絵文字を選ぶ。気象庁は対応表を公開していないので自前。

    天気コードは先頭の桁が 1=晴れ 2=くもり 3=雨 4=雪 という決まりになっている。
    """
    t = text or ""
    for word, icon in (("雪", "❄"), ("雨", "☔"), ("くもり", "☁"), ("曇", "☁"), ("晴", "☀")):
        if word in t:
            return icon
    if code:
        return {"1": "☀", "2": "☁", "3": "☔", "4": "❄"}.get(code[0], "・")
    return "・"


def weather_from_code(code: str | None) -> str:
    """週間予報は天気の文字が無くコードだけなので、大まかな天気名に直す。"""
    if not code:
        return "―"
    return {"1": "晴れ", "2": "くもり", "3": "雨", "4": "雪"}.get(code[0], "―")


# ---------------------------------------------------------------- データ構造
@dataclass
class WarningItem:
    """1 つの警報・注意報と、それが出ている細分区域の名前。"""
    code: str
    areas: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return warning_name(self.code)

    @property
    def level(self) -> str:
        return warning_level(self.code)

    @property
    def level_label(self) -> str:
        return LEVEL_LABEL[self.level]


@dataclass
class PrefWarning:
    """都道府県 1 つ分の、いま出ている警報・注意報。"""
    pref: str
    report: datetime | None
    headlines: list[str]
    items: list[WarningItem]

    @property
    def name(self) -> str:
        return pref_name(self.pref)

    @property
    def slug(self) -> str:
        return pref_slug(self.pref)

    @property
    def path(self) -> str:
        return f"area/{self.slug}/"

    def of_level(self, level: str) -> list[WarningItem]:
        return [w for w in self.items if w.level == level]

    @property
    def emergencies(self) -> list[WarningItem]:
        return self.of_level(EMERGENCY)

    @property
    def warnings(self) -> list[WarningItem]:
        return self.of_level(WARNING)

    @property
    def advisories(self) -> list[WarningItem]:
        return self.of_level(ADVISORY)

    @property
    def top_level(self) -> str | None:
        """いちばん重い段階。何も出ていなければ None。"""
        for level in (EMERGENCY, WARNING, ADVISORY):
            if self.of_level(level):
                return level
        return None

    @property
    def has_warning(self) -> bool:
        """警報以上が出ているか（ランキングの数え方の基準）。"""
        return self.top_level in (EMERGENCY, WARNING)

    @property
    def summary(self) -> str:
        if not self.items:
            return "発表中の警報・注意報はありません"
        return "、".join(w.name for w in self.items)


@dataclass
class QuakePref:
    name: str
    max_int: str
    cities: list[tuple[str, str]]  # (市区町村名, 震度)


@dataclass
class Quake:
    """地震 1 件。震度速報・遠地地震など、震源や震度が欠けている形もある。"""
    id: str
    report: datetime | None
    origin: datetime | None
    kind: str
    place: str
    magnitude: str
    lat: float | None
    lon: float | None
    depth: float | None
    max_int: str
    prefs: list[QuakePref]
    comment: str

    @property
    def path(self) -> str:
        return f"quake/{self.id}/"

    @property
    def when(self) -> datetime | None:
        return self.origin or self.report

    @property
    def rank(self) -> int:
        return intensity_rank(self.max_int)

    @property
    def max_int_label(self) -> str:
        return intensity_label(self.max_int)

    @property
    def magnitude_label(self) -> str:
        if not self.magnitude or "不明" in self.magnitude:
            return "不明"
        return f"M{self.magnitude}"

    @property
    def depth_label(self) -> str:
        if self.depth is None:
            return "不明"
        if self.depth < 1:
            return "ごく浅い"
        return f"約{int(round(self.depth))}km"

    @property
    def title(self) -> str:
        place = self.place or "震源不明"
        if self.rank >= 0:
            return f"{place}の地震（最大{self.max_int_label}）"
        return f"{place}の地震"

    def affected_prefs(self) -> list[str]:
        """震度を観測した都道府県の名前。"""
        return [p.name for p in self.prefs]
