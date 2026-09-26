# 防災ウォッチ

気象庁の公開データから、**いま出ている警報・注意報**、**今日と明日の天気**、**最近の地震**を
1 時間ごとに取り込み、静的サイトとして GitHub Pages に配信する。**運用費ゼロ**
（気象庁の JSON はキー不要、GitHub Actions と Pages は無料枠）。人手は一切入らない。

- 公開先: https://bosai-watch.rakunowa.workers.dev/
- 出典はすべて **気象庁**（https://www.jma.go.jp/bosai/ が読んでいるのと同じ公開 JSON）

## 仕組み

```
気象庁の公開 JSON ──fetch──▶ data/current/warning/<気象台>.json   いま出ている警報（毎回上書き）
                             data/current/forecast/<気象台>.json  今日〜週間の予報（毎回上書き）
                             data/quakes/<地震 ID>.json           地震 1 件（貯まっていく）
                             data/history/<日付>.json             その日に観測した警報（貯まっていく）
                                        │
                                        └──build──▶ dist/ ──▶ GitHub Pages
```

- `bosai/model.py` 意味の対応表（警報コード・震度・都道府県）と小さなデータ構造。ネットワークに触らない。
- `bosai/jma.py` 取り込み。大きな JSON はその場で必要な分だけ抜き出して捨てる（メモリ節約）。
- `bosai/history.py` 日ごとの観測記録の読み書きと、ランキングの集計。
- `bosai/build.py` Jinja2 で `dist/` を書き出す。
- `.github/workflows/hourly.yml` 1 時間ごとに fetch → データをコミット → テスト → build → Pages に配信。

### 使っている気象庁の JSON

| 用途 | URL |
| --- | --- |
| 警報・注意報 | `bosai/warning/data/warning/<気象台コード>.json` |
| 天気予報・週間予報 | `bosai/forecast/data/forecast/<気象台コード>.json` |
| 地震一覧 | `bosai/quake/data/list.json` |
| 地震の詳細 | `bosai/quake/data/<一覧の json 欄>` |
| 区域コードと名前 | `bosai/common/const/area.json` |

気象台（office）は 58 か所。**コードの先頭 2 桁が都道府県の JIS コード**になっているので、
それを使って 47 都道府県にまとめ直している（北海道は 8 か所、沖縄は 4 か所、鹿児島は 2 か所に分かれる）。
予報が出ない気象台が 2 つある（十勝は釧路、奄美は鹿児島の予報に含まれる）ので、そこは飛ばす。

### 警報コードについて

気象庁は**警報コードの対応表を JSON で公開していない**（`bosai/const/warning_codes.json` は 404）。
そのため `bosai/model.py` の `WARNING_CODES` に自前で持っている。
**特別警報 → 警報 → 注意報** の 3 段階で色を分け、status が「解除」のものは出ていない扱いにする。
コードを足すときはここだけ直せばよい。

## 生成されるページ

| パス | 内容 |
| --- | --- |
| `/` | トップ。いま警報が出ている都道府県、注意報の都道府県、最近の地震、今月の震度4以上、ランキング、47 都道府県の入口 |
| `/area/` | 都道府県の一覧（地方ごと。左の色で段階が分かる） |
| `/area/<slug>/` | 都道府県 1 つ。警報・注意報（種類ごと・区域つき）、今日〜明後日の天気と降水確率、気温、週間予報、その県で揺れた直近の地震 |
| `/quake/` | 最近の地震 100 件 |
| `/quake/<地震 ID>/` | 地震 1 件。発生時刻・震源・規模・最大震度・各地の震度 |
| `/quake/strong/` `/quake/strong/<年-月>/` | 震度4以上の地震の月ごとのまとめ |
| `/ranking/` | 警報が出た回数の都道府県ランキング |
| `/about/` `/privacy/` `/404.html` | 固定ページ |
| `/feed.xml` `/sitemap.xml` `/robots.txt` | RSS（警報の発表と震度3以上の地震）・サイトマップ |

全ページに canonical・OGP・構造化データ（WebSite / BreadcrumbList / CollectionPage）を出す。

## ランキングの数え方

気象庁は「過去にどの県に何回警報が出たか」を配っていない。そこで 1 時間ごとの取り込みのたびに
「そのとき出ていた警報・注意報」を `data/history/<日付>.json` に足し込み、その積み重ねから数えている。
**当サイトが観測できた分の累積**であって、気象庁の公式統計ではない。この断りはページにも出している。

## コマンド（`.venv` を使う）

```powershell
.\.venv\Scripts\python -m bosai fetch                                      # 気象庁から取り込む
.\.venv\Scripts\python -m bosai build --site-url http://127.0.0.1:8000     # ローカル確認用に生成
.\.venv\Scripts\python -m http.server 8000 -d dist                         # http://127.0.0.1:8000/
.\.venv\Scripts\python -m bosai all                                        # fetch → build
.\.venv\Scripts\python -m pytest -q
```

初回の `fetch` は地震の詳細を 200 件ほど取るので 2 分ほどかかる。2 回目以降は新しい地震の分だけ。

## data/ の扱い

- `data/quakes/` と `data/history/` は **コミットする**（履歴として積み上がるもの）。
- `data/current/` は毎回取り直すだけなので `.gitignore` に入れている。

## 設定

`config/site.json`。`site_url` は Pages の URL。サイト名・説明・出典の表記もここ。
