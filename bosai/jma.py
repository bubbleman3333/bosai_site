"""気象庁の公開 JSON を取り込んで data/ に貯める。

気象庁のサイト https://www.jma.go.jp/bosai/ が読んでいるのと同じ JSON。キーもログインも要らない。

- 警報・注意報  warning/data/warning/<気象台コード>.json
- 天気予報      forecast/data/forecast/<気象台コード>.json
- 地震一覧      quake/data/list.json（各地震の詳細は同じ階層の json）
- 区域の名前    common/const/area.json

気象台（office）は 58 個ある。北海道は 8 つ、沖縄は 4 つに分かれていて、
コードの先頭 2 桁が都道府県の JIS コードになっている（model.pref_of_office）。

取り込んだものは次の形で置く。
  data/current/warning/<気象台>.json   いま出ている警報・注意報（毎回上書き）
  data/current/forecast/<気象台>.json  今日〜週間の予報（毎回上書き）
  data/quakes/<地震 ID>.json           地震 1 件（一度書いたら基本そのまま。履歴として貯まる）
  data/history/<日付>.json             その日に観測した警報・注意報（ランキングの元。append）

メモリを節約するため、取ってきた大きな JSON はその場で必要な分だけ抜き出し、すぐ捨てる。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests

from .history import record_day
from .model import JST, is_active, parse_coordinate, parse_dt, pref_of_office, sort_warning_codes

BASE = "https://www.jma.go.jp/bosai"
AREA_URL = f"{BASE}/common/const/area.json"
WARNING_URL = BASE + "/warning/data/warning/{code}.json"
FORECAST_URL = BASE + "/forecast/data/forecast/{code}.json"
QUAKE_LIST_URL = f"{BASE}/quake/data/list.json"
QUAKE_DETAIL_URL = BASE + "/quake/data/{name}"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# 予報が出ない気象台（十勝は釧路、奄美は鹿児島の予報に入っている）
NO_FORECAST = {"014030", "460040"}
# 地震の詳細ページを作らない種類（地震そのものの情報ではないもの）
SKIP_QUAKE_TITLES = {"南海トラフ地震関連解説情報"}
# 一度に取り直す地震の詳細の上限。初回は多いので分けて取れるようにしておく
QUAKE_LIMIT = 400


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "bosai-watch/1.0 (+https://github.com/bubbleman3333/bosai_site)"
    return s


def _get(session: requests.Session, url: str, tries: int = 3):
    last: Exception | None = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - ネットワークは何が来てもやり直す
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"気象庁の JSON に失敗: {url}: {last}")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------- 区域の名前
def fetch_areas(session: requests.Session) -> tuple[dict[str, str], dict[str, str]]:
    """area.json から「細分区域コード → 名前」と「気象台コード → 名前」を作る。

    area.json は 260KB ほどある。必要な名前だけ取り出して、元の辞書はすぐ捨てる。
    """
    raw = _get(session, AREA_URL) or {}
    names = {code: v.get("name", code) for code, v in (raw.get("class10s") or {}).items()}
    offices = {code: v.get("name", code) for code, v in (raw.get("offices") or {}).items()}
    del raw
    return names, offices


# ---------------------------------------------------------------- 警報・注意報
def condense_warning(raw: dict, office: str, office_name: str, area_names: dict[str, str]) -> dict:
    """警報 JSON から「いま出ている分」だけを残す。

    areaTypes[0] が一次細分区域（東京地方・伊豆諸島北部など）、[1] が市町村。
    ページに出すのは一次細分区域だけにして軽くする。status が「解除」のものは出ていない扱い。
    """
    items: dict[str, list[str]] = {}
    for area in (raw.get("areaTypes") or [{}])[0].get("areas") or []:
        name = area_names.get(area.get("code", ""), area.get("code", ""))
        for w in area.get("warnings") or []:
            code = w.get("code")
            if code and is_active(w.get("status")):
                items.setdefault(code, []).append(name)
    headline = (raw.get("headlineText") or "").strip()
    return {
        "office": office,
        "office_name": office_name,
        "pref": pref_of_office(office),
        "report": raw.get("reportDatetime"),
        "headline": headline,
        "warnings": [{"code": c, "areas": items[c]} for c in sort_warning_codes(items)],
    }


def fetch_warnings(session: requests.Session, offices: dict[str, str], area_names: dict[str, str],
                   sleep: float = 0.15, log=print) -> list[dict]:
    out = []
    for i, (code, name) in enumerate(sorted(offices.items()), 1):
        raw = _get(session, WARNING_URL.format(code=code))
        if raw is None:
            continue
        row = condense_warning(raw, code, name, area_names)
        del raw
        _write(DATA / "current" / "warning" / f"{code}.json", row)
        out.append(row)
        if i % 20 == 0:
            log(f"  警報 {i}/{len(offices)}")
        time.sleep(sleep)
    return out


# ---------------------------------------------------------------- 天気予報
def _series(block: dict, key: str) -> tuple[list[str], list[dict]]:
    """timeSeries の中から、指定の項目を持つものを探して (時刻の並び, 区域の並び) を返す。"""
    for ts in block.get("timeSeries") or []:
        areas = ts.get("areas") or []
        if areas and key in areas[0]:
            return ts.get("timeDefines") or [], areas
    return [], []


def condense_forecast(raw: list, office: str, office_name: str) -> dict:
    """予報 JSON から、今日からの 3 日分・降水確率・気温・週間予報を抜き出す。

    生の JSON は「時刻の並び」と「値の並び」が別々に入っている入れ子なので、
    ここで日付ごとの行に組み直しておく（テンプレート側で index を数えなくて済む）。
    """
    near, week = (raw + [{}, {}])[0], (raw + [{}, {}])[1]

    w_times, w_areas = _series(near, "weathers")
    p_times, p_areas = _series(near, "pops")
    t_times, t_areas = _series(near, "temps")

    pops_by_area: dict[str, list[dict]] = {}
    for a in p_areas:
        rows = []
        for t, v in zip(p_times, a.get("pops") or []):
            dt = parse_dt(t)
            if dt and v != "":
                rows.append({"date": dt.strftime("%Y-%m-%d"), "hour": dt.strftime("%H"), "pop": v})
        pops_by_area[a["area"]["code"]] = rows

    areas = []
    for a in w_areas:
        code = a["area"]["code"]
        days = []
        for i, t in enumerate(w_times):
            dt = parse_dt(t)
            if not dt:
                continue
            date = dt.strftime("%Y-%m-%d")
            pops = [r for r in pops_by_area.get(code, []) if r["date"] == date]
            days.append({
                "date": date,
                "weather": (a.get("weathers") or [""] * (i + 1))[i],
                "code": (a.get("weatherCodes") or [""] * (i + 1))[i],
                "wind": (a.get("winds") or [""] * (i + 1))[i],
                "wave": (a.get("waves") or [""] * (i + 1))[i] if a.get("waves") else "",
                "pops": pops,
                "pop_max": max((int(r["pop"]) for r in pops), default=None),
            })
        areas.append({"code": code, "name": a["area"]["name"], "days": days})

    temps = []
    for a in t_areas:
        rows = []
        for t, v in zip(t_times, a.get("temps") or []):
            dt = parse_dt(t)
            if dt and v != "":
                rows.append({"date": dt.strftime("%Y-%m-%d"), "hour": dt.strftime("%H"), "temp": v})
        if rows:
            temps.append({"name": a["area"]["name"], "rows": rows})

    wk_times, wk_areas = _series(week, "weatherCodes")
    wt_times, wt_areas = _series(week, "tempsMax")
    weekly = []
    for a in wk_areas:
        rows = []
        for i, t in enumerate(wk_times):
            dt = parse_dt(t)
            if not dt:
                continue
            rows.append({"date": dt.strftime("%Y-%m-%d"),
                         "code": (a.get("weatherCodes") or [""] * (i + 1))[i],
                         "pop": (a.get("pops") or [""] * (i + 1))[i]})
        weekly.append({"name": a["area"]["name"], "rows": rows})
    weekly_temps = []
    for a in wt_areas:
        rows = []
        for i, t in enumerate(wt_times):
            dt = parse_dt(t)
            if not dt:
                continue
            rows.append({"date": dt.strftime("%Y-%m-%d"),
                         "min": (a.get("tempsMin") or [""] * (i + 1))[i],
                         "max": (a.get("tempsMax") or [""] * (i + 1))[i]})
        weekly_temps.append({"name": a["area"]["name"], "rows": rows})

    return {"office": office, "office_name": office_name, "pref": pref_of_office(office),
            "report": near.get("reportDatetime"), "areas": areas, "temps": temps,
            "weekly": weekly, "weekly_temps": weekly_temps}


def fetch_forecasts(session: requests.Session, offices: dict[str, str], sleep: float = 0.15, log=print) -> list[dict]:
    targets = {c: n for c, n in offices.items() if c not in NO_FORECAST}
    out = []
    for i, (code, name) in enumerate(sorted(targets.items()), 1):
        raw = _get(session, FORECAST_URL.format(code=code))
        if not raw:
            continue
        row = condense_forecast(raw, code, name)
        del raw
        _write(DATA / "current" / "forecast" / f"{code}.json", row)
        out.append(row)
        if i % 20 == 0:
            log(f"  予報 {i}/{len(targets)}")
        time.sleep(sleep)
    return out


# ---------------------------------------------------------------- 地震
def condense_quake(row: dict, detail: dict | None) -> dict:
    """一覧の行と詳細 JSON から、ページに要るものだけを取り出す。

    種類によって中身が違う（震度速報には震源が無く、遠地地震には震度が無い）ので、
    無い項目は空で埋める。
    """
    body = (detail or {}).get("Body") or {}
    eq = body.get("Earthquake") or {}
    hypo = (eq.get("Hypocenter") or {}).get("Area") or {}
    lat, lon, depth = parse_coordinate(hypo.get("Coordinate") or row.get("cod"))

    prefs = []
    for p in ((body.get("Intensity") or {}).get("Observation") or {}).get("Pref") or []:
        cities: list[list[str]] = []
        for area in p.get("Area") or []:
            for city in area.get("City") or []:
                cities.append([city.get("Name", ""), city.get("MaxInt", "")])
            if not (area.get("City") or []):  # 震度速報は区域までしか分からない
                cities.append([area.get("Name", ""), area.get("MaxInt", "")])
        prefs.append({"name": p.get("Name", ""), "max_int": p.get("MaxInt", ""), "cities": cities})

    comments = body.get("Comments") or {}
    comment = ((comments.get("ForecastComment") or {}).get("Text") or "").strip()

    return {
        "id": row["eid"],
        "ctt": row.get("ctt", ""),
        "report": row.get("rdt"),
        "origin": eq.get("OriginTime") or row.get("at"),
        "kind": row.get("ttl", ""),
        "place": hypo.get("Name") or row.get("anm") or "",
        "magnitude": str(eq.get("Magnitude") or row.get("mag") or ""),
        "lat": lat, "lon": lon, "depth": depth,
        "max_int": row.get("maxi") or ((body.get("Intensity") or {}).get("Observation") or {}).get("MaxInt") or "",
        "prefs": prefs,
        "comment": comment,
    }


def fetch_quakes(session: requests.Session, limit: int = QUAKE_LIMIT, sleep: float = 0.15, log=print) -> int:
    """地震一覧を取り、まだ持っていない／報が更新された地震の詳細を取って保存する。"""
    rows = _get(session, QUAKE_LIST_URL) or []
    # 同じ地震（eid）について何報も出るので、いちばん新しい報だけ使う
    latest: dict[str, dict] = {}
    for row in rows:
        eid = row.get("eid")
        if not eid or row.get("ttl") in SKIP_QUAKE_TITLES:
            continue
        cur = latest.get(eid)
        if cur is None or (row.get("ctt", "") > cur.get("ctt", "")):
            latest[eid] = row
    del rows
    log(f"地震一覧: {len(latest)} 件")

    out_dir = DATA / "quakes"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for eid, row in latest.items():
        path = out_dir / f"{eid}.json"
        if not path.exists():
            todo.append((eid, row))
            continue
        try:
            old_ctt = json.loads(path.read_text(encoding="utf-8")).get("ctt", "")
        except (OSError, ValueError):
            old_ctt = ""
        if row.get("ctt", "") > old_ctt:
            todo.append((eid, row))
    todo = todo[:limit]
    log(f"詳細を取る: {len(todo)} 件")

    saved = 0
    for i, (eid, row) in enumerate(todo, 1):
        detail = _get(session, QUAKE_DETAIL_URL.format(name=row["json"])) if row.get("json") else None
        _write(out_dir / f"{eid}.json", condense_quake(row, detail))
        del detail
        saved += 1
        if i % 50 == 0:
            log(f"  地震 {i}/{len(todo)}")
        time.sleep(sleep)
    return saved


# ---------------------------------------------------------------- まとめ
def sync(log=print, now: datetime | None = None) -> dict:
    """全部取り込む。1 時間に 1 回、GitHub Actions から呼ばれる。"""
    now = now or datetime.now(JST)
    session = _session()
    area_names, offices = fetch_areas(session)
    log(f"気象台 {len(offices)} か所")
    warnings = fetch_warnings(session, offices, area_names, log=log)
    forecasts = fetch_forecasts(session, offices, log=log)
    quakes = fetch_quakes(session, log=log)
    days = record_day(warnings, DATA / "history", now)
    log(f"警報 {len(warnings)} / 予報 {len(forecasts)} / 地震 {quakes} 件を保存。観測記録 {days}")
    return {"warnings": len(warnings), "forecasts": len(forecasts), "quakes": quakes}
