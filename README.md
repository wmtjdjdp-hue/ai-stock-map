# AI関連株コード辞典 Streamlit 試作版

## ファイル
- app.py：サイト本体
- stocks.csv：銘柄データ
- requirements.txt：Streamlit Cloudで必要なライブラリ

## ローカルで動かす方法

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloudで公開する方法

1. GitHubにこの3ファイルをアップロード
2. Streamlit Cloudで「New app」
3. Repositoryを選択
4. Main file pathに `app.py`
5. Deploy

## 銘柄を追加する方法

`stocks.csv` に1行追加してください。
