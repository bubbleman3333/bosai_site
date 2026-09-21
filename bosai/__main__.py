"""使い方:
  python -m bosai fetch                                   気象庁から取り込む
  python -m bosai build [--out dist] [--site-url URL]     サイトを生成
  python -m bosai all                                     fetch → build
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import ROOT, Builder


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="bosai", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    for name in ("build", "all"):
        s = sub.add_parser(name)
        s.add_argument("--out", default="dist")
        s.add_argument("--site-url", default=None)
    args = p.parse_args(argv)

    site = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    if args.cmd in ("fetch", "all"):
        from .jma import sync  # requests は build には要らないのでここで読む
        sync()
    if args.cmd in ("build", "all"):
        n = Builder(Path(args.out), args.site_url or site["site_url"]).build()
        print(f"{args.out}/ に {n} ページを生成した")


if __name__ == "__main__":
    main()
