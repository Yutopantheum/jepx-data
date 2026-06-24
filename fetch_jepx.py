#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# JEPX スポット市場（システムプライス）を取得して data.json を作る。
# 追加インストール不要（Python標準ライブラリだけ）。GitHub Actions から毎日実行する想定。
import urllib.request, urllib.parse, csv, io, json, re, datetime
from collections import OrderedDict

JST = datetime.timezone(datetime.timedelta(hours=9))


def fiscal_year(d):
    # 日本の年度は4月始まり。1〜3月は前年の年度。
    return d.year if d.month >= 4 else d.year - 1


def fetch_text(fy):
    """いくつかの取得方法を順に試し、日付行が見つかったCSV本文を返す。"""
    attempts = []
    # (1) 新サイト jepx.jp : POST /_download.php
    try:
        body = urllib.parse.urlencode(
            {"dir": "spot_summary", "file": f"spot_summary_{fy}.csv"}
        ).encode()
        req = urllib.request.Request(
            "https://www.jepx.jp/_download.php", data=body,
            headers={
                "Referer": "https://www.jepx.jp/electricpower/market-data/spot/",
                "User-Agent": "Mozilla/5.0 (jepx-data-fetcher)",
            },
        )
        attempts.append(("jepx.jp POST", urllib.request.urlopen(req, timeout=60).read()))
    except Exception as e:
        print(f"  [skip] jepx.jp POST: {e}")
    # (2) 旧サイト jepx.org : GET（予備）
    for name in (f"spot_summary_{fy}.csv", f"spot_{fy}.csv"):
        try:
            url = f"http://www.jepx.org/market/excel/{name}"
            attempts.append((f"jepx.org {name}", urllib.request.urlopen(url, timeout=60).read()))
        except Exception as e:
            print(f"  [skip] jepx.org {name}: {e}")

    for label, raw in attempts:
        text = raw.decode("shift_jis", errors="replace")
        n = len(re.findall(r"^\d{4}/\d{1,2}/\d{1,2},", text, re.M))
        print(f"  tried {label}: {n} date-rows")
        if n > 0:
            return text
    return None


def parse(text):
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        if not re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", row[0].strip()):
            continue
        try:
            d = datetime.datetime.strptime(row[0].strip(), "%Y/%m/%d")
            code = int(row[1])          # 1〜48（30分コマ）
            v = float(row[5])           # システムプライス(円/kWh)
        except Exception:
            continue
        dt = d.replace(tzinfo=JST) + datetime.timedelta(minutes=30 * (code - 1))
        out.append({"t": int(dt.timestamp() * 1000), "v": round(v, 2)})
    return out


def main():
    today = datetime.datetime.now(JST)
    fy = fiscal_year(today)
    records = []
    for y in (fy, fy - 1):              # 今年度＋前年度ぶん集める（履歴を厚く）
        print(f"fiscal year {y}:")
        text = fetch_text(y)
        if text:
            records += parse(text)

    records = list({r["t"]: r for r in records}.values())   # 重複除去
    records.sort(key=lambda r: r["t"])
    if not records:
        raise SystemExit("ERROR: データを取得できませんでした。"
                         "JEPXの仕様変更の可能性。URL/年度を確認してください。")

    # intraday（30分）: 直近14日ぶん
    cutoff = records[-1]["t"] - 14 * 86400000
    intraday = [r for r in records if r["t"] >= cutoff]

    # daily（日次）: JST日付ごとの平均
    buckets = OrderedDict()
    for r in records:
        day = datetime.datetime.fromtimestamp(r["t"] / 1000, JST).date()
        buckets.setdefault(day, []).append(r["v"])
    daily = []
    for day, vs in buckets.items():
        noon = datetime.datetime.combine(day, datetime.time(12, 0), JST)
        daily.append({"t": int(noon.timestamp() * 1000), "v": round(sum(vs) / len(vs), 2)})

    out = {
        "spotDaily": daily,
        "spotIntraday": intraday,
        "updated": today.isoformat(),
        "rows": len(records),
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"OK: daily={len(daily)} intraday={len(intraday)} -> data.json")


if __name__ == "__main__":
    main()
