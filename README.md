# AI関連株コード辞典 v4 Multi Source

## v4で追加した機能
- yfinance + FMP + Alpha Vantage の複数ソース補完
- 各項目の取得元表示
- APIキー未設定でも yfinance のみで動作
- Streamlit Secrets からAPIキーを読み込み
- 外部調査リンクは継続

## GitHubで上書きするファイル
- app.py
- stocks.csv
- requirements.txt
- README.md

## Streamlit CloudでAPIキーを設定する方法

Streamlit Cloudのアプリ管理画面で、

Settings → Secrets

を開いて、以下のように入力します。

```toml
FMP_API_KEY = "ここにFMPのAPIキー"
ALPHAVANTAGE_API_KEY = "ここにAlpha VantageのAPIキー"
```

片方だけでもOKです。

## 無料APIの注意
無料APIには回数制限、対象市場制限、表示・利用条件があります。
公開サイトとして使う場合は各サービスの規約確認が必要です。
