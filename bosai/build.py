"""data/ から dist/ に静的サイトを書き出す。"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .history import load_days, tally
from .model import (EMERGENCY, JST, LEVEL_LABEL, PREFECTURES, REGIONS, WARNING, PrefWarning, Quake, QuakePref,
                    WarningItem, intensity_class, intensity_label, intensity_rank, parse_dt, pref_name, pref_slug,
                    warning_level, warning_name, weather_from_code, weather_icon)

ROOT = Path(__file__).resolve().parent.parent
QUAKE_LIST_MAX = 100     # 地震一覧に出す件数
STRONG_INTENSITY = "4"   # 「大きな地震」として別にまとめる震度
FEED_MAX = 40
WEEKDAYS = "月火水木金土日"


def fmt_dt(d: datetime | None, with_time: bool = True) -> str:
    if not d:
        return "不明"
    s = f"{d.year}年{d.month}月{d.day}日"
    return s + (f" {d:%H:%M}" if with_time else "")


def fmt_day(value: str | None) -> str:
    """'2026-09-22' → '9月22日(火)'。"""
    d = parse_dt(value + "T00:00:00+09:00") if value and len(value) == 10 else None
    if not d:
        return value or ""
    return f"{d.month}月{d.day}日({WEEKDAYS[d.weekday()]})"


def load_warnings(data_dir: Path) -> list[PrefWarning]:
    """気象台ごとのファイルを都道府県にまとめ直す（北海道は 8 台、沖縄は 4 台に分かれている）。"""
    by_pref: dict[str, dict] = {}
    for path in sorted((data_dir / "current" / "warning").glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slot = by_pref.setdefault(row["pref"], {"report": None, "headlines": [], "items": {}})
        report = parse_dt(row.get("report"))
        if report and (slot["report"] is None or report > slot["report"]):
            slot["report"] = report
        if row.get("headline") and row["headline"] not in slot["headlines"]:
            slot["headlines"].append(row["headline"])
        for w in row.get("warnings") or []:
            slot["items"].setdefault(w["code"], []).extend(w["areas"])

    out = []
    for code in PREFECTURES:
        slot = by_pref.get(code, {"report": None, "headlines": [], "items": {}})
        items = [WarningItem(c, sorted(set(a))) for c, a in slot["items"].items()]
        items.sort(key=lambda w: (0 if w.level == EMERGENCY else 1 if w.level == WARNING else 2, w.code))
        out.append(PrefWarning(code, slot["report"], slot["headlines"], items))
    return out


def load_forecasts(data_dir: Path) -> dict[str, list[dict]]:
    by_pref: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((data_dir / "current" / "forecast").glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        by_pref[row["pref"]].append(row)
    return by_pref


def load_quakes(data_dir: Path) -> list[Quake]:
    out = []
    for path in sorted((data_dir / "quakes").glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append(Quake(
            id=raw["id"], report=parse_dt(raw.get("report")), origin=parse_dt(raw.get("origin")),
            kind=raw.get("kind", ""), place=raw.get("place", ""), magnitude=raw.get("magnitude", ""),
            lat=raw.get("lat"), lon=raw.get("lon"), depth=raw.get("depth"), max_int=raw.get("max_int", ""),
            # 気象庁の並びは区域順なので、読む人のために震度の強い順に並べ替える
            prefs=[QuakePref(p.get("name", ""), p.get("max_int", ""),
                             sorted(((c[0], c[1]) for c in p.get("cities") or []),
                                    key=lambda c: intensity_rank(c[1]), reverse=True))
                   for p in sorted(raw.get("prefs") or [], key=lambda p: intensity_rank(p.get("max_int")), reverse=True)],
            comment=raw.get("comment", ""),
        ))
    out.sort(key=lambda q: q.when or datetime.min.replace(tzinfo=JST), reverse=True)
    return out


class Builder:
    def __init__(self, out_dir: Path, site_url: str, now: datetime | None = None,
                 data_dir: Path | None = None, root: Path = ROOT):
        self.out = Path(out_dir)
        self.site_url = site_url.rstrip("/")
        self.now = now or datetime.now(JST)
        self.root = Path(root)
        self.data_dir = Path(data_dir) if data_dir else self.root / "data"
        self.site = json.loads((self.root / "config" / "site.json").read_text(encoding="utf-8"))
        self.env = Environment(loader=FileSystemLoader(str(self.root / "templates")),
                               autoescape=select_autoescape(["html", "xml"]))
        self.env.filters["dt"] = fmt_dt
        self.env.filters["date"] = lambda d: fmt_dt(d, with_time=False)
        self.env.filters["day"] = fmt_day
        self.env.globals.update(url=self.url, site=self.site, now=self.now, LEVEL_LABEL=LEVEL_LABEL,
                                intensity_label=intensity_label, intensity_class=intensity_class,
                                intensity_rank=intensity_rank, weather_icon=weather_icon,
                                weather_from_code=weather_from_code, REGIONS=REGIONS, pref_name=pref_name,
                                pref_slug=pref_slug, warning_name=warning_name, warning_level=warning_level)
        self.sitemap: list[tuple[str, datetime | None]] = []

    # ---- 部品 ----
    def url(self, path: str = "") -> str:
        return f"{self.site_url}/{path.lstrip('/')}"

    def write(self, path: str, text: str) -> None:
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def render(self, template: str, path: str, *, noindex: bool = False, lastmod: datetime | None = None, **ctx) -> None:
        canonical = self.url(path.replace("index.html", ""))
        crumbs = ctx.pop("crumbs", [])
        self.write(path, self.env.get_template(template).render(
            canonical=canonical, noindex=noindex, crumbs=crumbs, breadcrumb_json=self.breadcrumb(crumbs, canonical), **ctx))
        if not noindex:
            self.sitemap.append((canonical, lastmod))

    def breadcrumb(self, crumbs: list[tuple[str, str]], canonical: str) -> str:
        """パンくずの構造化データ。crumbs は [(表示名, パス)] で、最後の 1 つが今のページ。"""
        items = [{"@type": "ListItem", "position": 1, "name": "ホーム", "item": self.url()}]
        for i, (name, path) in enumerate(crumbs, 2):
            items.append({"@type": "ListItem", "position": i, "name": name,
                          "item": self.url(path) if path else canonical})
        return json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items},
                          ensure_ascii=False, separators=(",", ":"))

    # ---- 本体 ----
    def build(self) -> int:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(self.root / "static", self.out / "static")

        prefs = load_warnings(self.data_dir)
        by_code = {p.pref: p for p in prefs}
        forecasts = load_forecasts(self.data_dir)
        quakes = load_quakes(self.data_dir)
        stats = tally(load_days(self.data_dir / "history"))

        alerting = [p for p in prefs if p.has_warning]
        advising = [p for p in prefs if not p.has_warning and p.items]
        quiet = [p for p in prefs if not p.items]
        recent = quakes[:QUAKE_LIST_MAX]
        felt = [q for q in quakes if q.rank >= 0]
        strong = [q for q in quakes if q.rank >= intensity_rank(STRONG_INTENSITY)]
        latest_report = max((p.report for p in prefs if p.report), default=None)

        quakes_by_pref: dict[str, list[Quake]] = defaultdict(list)
        for q in quakes:
            for name in q.affected_prefs():
                quakes_by_pref[name].append(q)

        months: dict[str, list[Quake]] = defaultdict(list)
        for q in strong:
            if q.when:
                months[q.when.strftime("%Y-%m")].append(q)
        month_keys = sorted(months, reverse=True)
        this_month = self.now.strftime("%Y-%m")

        self.env.globals.update(
            nav_alerting=alerting,
            sidebar_quakes=felt[:6],
            all_prefs=prefs,
            footer_stats=dict(prefs=len(prefs), quakes=len(quakes), days=stats["days"],
                              alerting=len(alerting), advising=len(advising), updated=self.now,
                              report=latest_report),
        )

        # トップ
        self.render("index.html", "index.html", title=self.site["name"], description=self.site["description"],
                    alerting=alerting, advising=advising, quiet=quiet, prefs=prefs, by_code=by_code,
                    quakes=felt[:8], strong_month=months.get(this_month, []), this_month=this_month,
                    ranking=stats["ranking"][:10], stats=stats, lastmod=self.now)

        # 都道府県
        self.render("areas.html", "area/index.html", title="都道府県から見る",
                    description="47 都道府県の警報・注意報と天気を一覧で。気になる県のページで、今日明日の天気・降水確率・直近の地震まで見られます。",
                    prefs=prefs, by_code=by_code, crumbs=[("都道府県から見る", "")], lastmod=self.now)
        for p in prefs:
            fc = forecasts.get(p.pref, [])
            self.render("area.html", f"{p.path}index.html",
                        title=f"{p.name}の警報・注意報と天気", description=self.area_description(p),
                        p=p, forecasts=fc, quakes=quakes_by_pref.get(p.name, [])[:10],
                        rank=next((r for r in stats["ranking"] if r["pref"] == p.pref), None),
                        crumbs=[("都道府県から見る", "area/"), (p.name, "")], lastmod=self.now)

        # 地震
        self.render("quakes.html", "quake/index.html", title="最近の地震",
                    description=f"気象庁が発表した地震の情報を新しい順に {min(len(recent), QUAKE_LIST_MAX)} 件。発生時刻・震源・規模・最大震度が分かります。",
                    items=recent, crumbs=[("最近の地震", "")], lastmod=self.now)
        for q in quakes:
            self.render("quake.html", f"{q.path}index.html", title=q.title,
                        description=self.quake_description(q), q=q,
                        related=[r for r in quakes if r is not q and r.rank >= 0][:6],
                        crumbs=[("最近の地震", "quake/"), (q.title, "")], lastmod=q.report or q.when)

        self.render("months.html", "quake/strong/index.html", title=f"震度{STRONG_INTENSITY}以上の地震まとめ",
                    description=f"震度{STRONG_INTENSITY}以上を観測した地震を月ごとにまとめています。",
                    rows=[(m, len(months[m])) for m in month_keys],
                    crumbs=[("最近の地震", "quake/"), (f"震度{STRONG_INTENSITY}以上", "")], lastmod=self.now)
        for m in month_keys:
            y, mo = m.split("-")
            self.render("quakes.html", f"quake/strong/{m}/index.html",
                        title=f"{y}年{int(mo)}月の震度{STRONG_INTENSITY}以上の地震",
                        description=f"{y}年{int(mo)}月に震度{STRONG_INTENSITY}以上を観測した地震 {len(months[m])} 件のまとめです。",
                        items=months[m], month=m,
                        crumbs=[("最近の地震", "quake/"), (f"震度{STRONG_INTENSITY}以上", "quake/strong/"),
                                (f"{y}年{int(mo)}月", "")], lastmod=self.now)

        # ランキング
        self.render("ranking.html", "ranking/index.html", title="警報が出た回数の都道府県ランキング",
                    description="当サイトが 1 時間ごとに記録した「警報・注意報が出ていた日」を都道府県ごとに数えたランキングです。",
                    stats=stats, crumbs=[("警報回数ランキング", "")], lastmod=self.now)

        # 固定ページ
        for name, title in (("about", "このサイトについて"), ("privacy", "プライバシーポリシー")):
            body = (self.root / "content" / f"{name}.html").read_text(encoding="utf-8")
            self.render("page.html", f"{name}/index.html", title=title, description=title, body=body,
                        crumbs=[(title, "")])
        self.write("404.html", self.env.get_template("404.html").render(
            canonical=self.url("404.html"), noindex=True, crumbs=[], breadcrumb_json=""))

        # 機械向け
        self.write_feed(alerting, [q for q in quakes if q.rank >= intensity_rank("3")])
        self.write_sitemap()
        self.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {self.url('sitemap.xml')}\n")
        self.write(".nojekyll", "")
        return len(self.sitemap)

    def area_description(self, p: PrefWarning) -> str:
        if p.items:
            return f"{p.name}に出ている警報・注意報は{p.summary}。今日と明日の天気・降水確率、直近の地震もまとめています。出典は気象庁。"
        return f"{p.name}に発表中の警報・注意報はありません。今日と明日の天気・降水確率、直近の地震をまとめています。出典は気象庁。"

    def quake_description(self, q: Quake) -> str:
        when = fmt_dt(q.when)
        head = f"{when}ごろ、{q.place or '震源不明'}を震源とする地震がありました。"
        return head + f"規模は{q.magnitude_label}、深さ{q.depth_label}、最大震度は{q.max_int_label}です。出典は気象庁。"

    def write_sitemap(self) -> None:
        rows = []
        for loc, lastmod in self.sitemap:
            lm = f"<lastmod>{lastmod:%Y-%m-%d}</lastmod>" if lastmod else ""
            rows.append(f"<url><loc>{escape(loc)}</loc>{lm}</url>")
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n")

    def write_feed(self, alerting: list[PrefWarning], quakes: list[Quake]) -> None:
        """RSS は「警報が出ている都道府県」と「震度 3 以上の地震」。新しい順に混ぜる。"""
        entries: list[tuple[datetime, str]] = []
        for p in alerting:
            when = p.report or self.now
            link = escape(self.url(p.path))
            heavy = p.emergencies + p.warnings
            names = "・".join(w.name for w in heavy)
            areas = "、".join(sorted({a for w in heavy for a in w.areas}))
            title = escape(f"【警報】{p.name}に{names}")
            guid = escape(self.url(p.path) + when.strftime("%Y%m%d%H%M"))
            body = escape(f"{p.name}に{names}が発表されています。対象は{areas}。")
            entries.append((when, f"<item><title>{title}</title><link>{link}</link>"
                                  f'<guid isPermaLink="false">{guid}</guid>'
                                  f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
                                  f"<description>{body}</description></item>"))
        for q in quakes[:FEED_MAX]:
            when = q.when or self.now
            link = escape(self.url(q.path))
            place = q.place or "震源不明"
            title = escape(f"【{q.max_int_label}】{place}（{q.magnitude_label}）")
            entries.append((when, f"<item><title>{title}</title>"
                                  f'<link>{link}</link><guid isPermaLink="false">{link}</guid>'
                                  f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
                                  f"<description>{escape(self.quake_description(q))}</description></item>"))
        entries.sort(key=lambda t: t[0], reverse=True)
        self.write("feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
                   f"<title>{escape(self.site['name'])}</title><link>{escape(self.url())}</link>"
                   f"<description>{escape(self.site['description'])}</description>"
                   f"<language>ja</language><lastBuildDate>{self.now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>\n"
                   + "\n".join(html for _, html in entries[:FEED_MAX]) + "\n</channel></rss>\n")
