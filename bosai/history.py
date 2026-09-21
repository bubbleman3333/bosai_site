"""日ごとの観測結果（data/history/）の読み書きと集計。

気象庁は「過去にどの県に何回警報が出たか」を配っていない。
そこで、1 時間ごとの取り込みのたびに「そのとき出ていた警報・注意報」を日付ごとのファイルに足していき、
その積み重ねからランキングを作る。つまりこの数字は **当サイトが観測できた分の累積** であって、
気象庁の公式な統計ではない。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .model import ADVISORY, EMERGENCY, JST, WARNING, pref_name, pref_slug, sort_warning_codes, warning_level

LEVEL_KEYS = (EMERGENCY, WARNING, ADVISORY)


def day_path(history_dir: Path, day: datetime) -> Path:
    return history_dir / f"{day.strftime('%Y-%m-%d')}.json"


def record_day(warning_rows: list[dict], history_dir: Path, now: datetime | None = None) -> str:
    """取り込んだ警報を、その日のファイルに足し込む（同じ日に何度呼んでも和集合になる）。"""
    now = now or datetime.now(JST)
    path = day_path(history_dir, now)
    data = {"date": now.strftime("%Y-%m-%d"), "updated": "", "observations": 0, "prefs": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass

    prefs: dict[str, dict[str, list[str]]] = data.setdefault("prefs", {})
    for row in warning_rows:
        pref = row.get("pref")
        if not pref:
            continue
        slot = prefs.setdefault(pref, {k: [] for k in LEVEL_KEYS})
        for w in row.get("warnings") or []:
            level = warning_level(w["code"])
            bucket = slot.setdefault(level, [])
            if w["code"] not in bucket:
                bucket.append(w["code"])
    for slot in prefs.values():
        for level in LEVEL_KEYS:
            slot[level] = sort_warning_codes(slot.get(level, []))

    data["updated"] = now.isoformat(timespec="seconds")
    data["observations"] = int(data.get("observations", 0)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data["date"]


def load_days(history_dir: Path) -> list[dict]:
    """日ごとのファイルを古い順に読む。1 日分ずつしかメモリに持たないよう、必要な形に潰してから返す。"""
    out = []
    if not history_dir.exists():
        return out
    for path in sorted(history_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("date"):
            out.append(data)
    return out


def tally(days: list[dict]) -> dict:
    """都道府県ごとの「警報が出た日数」「注意報が出た日数」と、警報・注意報の種類ごとの日数。

    戻り値の ranking は警報が出た日数の多い順。
    """
    warn_days: dict[str, int] = defaultdict(int)
    adv_days: dict[str, int] = defaultdict(int)
    code_days: dict[str, int] = defaultdict(int)
    pref_codes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for day in days:
        for pref, slot in (day.get("prefs") or {}).items():
            emergencies = slot.get(EMERGENCY) or []
            warnings = slot.get(WARNING) or []
            advisories = slot.get(ADVISORY) or []
            if emergencies or warnings:
                warn_days[pref] += 1
            if advisories:
                adv_days[pref] += 1
            for code in emergencies + warnings + advisories:
                pref_codes[pref][code] += 1
        seen_today: set[str] = set()
        for slot in (day.get("prefs") or {}).values():
            for level in LEVEL_KEYS:
                seen_today.update(slot.get(level) or [])
        for code in seen_today:
            code_days[code] += 1

    ranking = []
    for pref in set(list(warn_days) + list(adv_days) + list(pref_codes)):
        codes = pref_codes.get(pref, {})
        top = sorted(codes.items(), key=lambda t: (-t[1], t[0]))[:3]
        ranking.append({
            "pref": pref,
            "name": pref_name(pref),
            "slug": pref_slug(pref),
            "warning_days": warn_days.get(pref, 0),
            "advisory_days": adv_days.get(pref, 0),
            "top_codes": [c for c, _ in top],
        })
    ranking.sort(key=lambda r: (-r["warning_days"], -r["advisory_days"], r["pref"]))
    return {
        "days": len(days),
        "first": days[0]["date"] if days else None,
        "last": days[-1]["date"] if days else None,
        "ranking": ranking,
        "code_days": sorted(code_days.items(), key=lambda t: (-t[1], t[0])),
    }
