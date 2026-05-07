# AI関連株コード辞典 v2

## 追加機能
- yfinanceによる株価・PER・PBR・時価総額などの自動取得
- Plotlyによる株価チャート
- ティッカー検索
- 関連図ハイライト
- 関連銘柄表示
- キーワード検索
- カテゴリ表示

## ファイル
- app.py
- stocks.csv
- requirements.txt
- README.md

## Streamlit Cloudで更新する方法
GitHub上で以下3ファイルを上書きしてください。

- app.py
- stocks.csv
- requirements.txt

その後、Streamlit Cloud側で自動的に再起動されます。
反映されない場合は、Streamlitの管理画面から Reboot app を押してください。

## 注意
株価・PER・PBR・時価総額は yfinance 経由の参考データです。
取得できない銘柄や項目があります。
投資判断は自己責任でお願いします。
