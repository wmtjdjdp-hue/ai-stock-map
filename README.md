# AI関連株コード辞典 v17 Japanese Translation

## v17で追加した内容
- 表示を「会社名」「ティッカーコード」に分離
- `AT&T Inc.` などは表示用に `AT&T` のように短く表示
- 英語で取得された事業内容を deep-translator 経由で日本語に自動翻訳
- 翻訳に失敗した場合は英語の原文を表示してアプリは止めない

## 追加ライブラリ
- deep-translator

# AI関連株コード辞典 v17 Japanese Translation

## v16で修正した内容
- 未登録ティッカーで会社名が `T` のようにティッカーだけになる問題を改善
- yfinanceで会社名が取れない場合、Yahoo Finance Search系の公開エンドポイントで会社名を補完
- 代表的な銘柄 `T` / `D` / `ARM` / `AAPL` / `MSFT` / `GOOGL` はローカル補完も追加
- 取得元表示に `Yahoo Search` が出る場合があります

# AI関連株コード辞典 v17 Japanese Translation

## v15で追加・整理したこと
- 登録済み銘柄は stocks.csv の情報を優先表示
- 未登録ティッカーでも検索可能
- 未登録ティッカーは yfinance / FMP / Finnhub / Alpha Vantage から以下を自動反映
  - 会社名
  - 分類 / セクター
  - 業種
  - 事業内容
  - AIとの仮関連メモ
  - 株価・PER・PBR・時価総額など
- スクレイピングではなくAPI/ライブラリのみ使用
- 最後に入力したティッカーを保持
- AI関連図へ登録可能

## Streamlit Secrets
App管理画面 → Settings → Secrets に以下を設定できます。

```toml
FMP_API_KEY = "ここにFMPのAPIキー"
FINNHUB_API_KEY = "ここにFinnhubのAPIキー"
ALPHAVANTAGE_API_KEY = "ここにAlpha VantageのAPIキー"
```

APIキーなしでも yfinance の範囲で動きますが、会社概要やPER/PBRは未取得になりやすいです。
