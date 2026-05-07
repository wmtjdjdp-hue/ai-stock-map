import streamlit as st
import pandas as pd
import streamlit.components.v1 as components
from pathlib import Path

st.set_page_config(
    page_title="AI関連株コード辞典",
    page_icon="📈",
    layout="wide",
)

@st.cache_data
def load_data():
    path = Path(__file__).parent / "stocks.csv"
    df = pd.read_csv(path)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["keywords"] = df["keywords"].fillna("")
    df["related"] = df["related"].fillna("")
    return df

df = load_data()

st.markdown(
    '''
    <style>
    .main-title {font-size:34px;font-weight:800;margin-bottom:4px;}
    .sub-title {color:#666;font-size:15px;margin-bottom:20px;}
    .card {background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;box-shadow:0 4px 18px rgba(0,0,0,0.05);margin-bottom:14px;}
    .ticker {font-size:30px;font-weight:800;}
    .company {font-size:20px;color:#444;margin-bottom:12px;}
    .badge {display:inline-block;background:#111827;color:white;padding:6px 10px;border-radius:999px;margin:3px 5px 3px 0;font-size:13px;}
    </style>
    ''',
    unsafe_allow_html=True,
)

st.sidebar.title("🔎 検索メニュー")
mode = st.sidebar.radio("検索方法", ["ティッカー検索", "キーワード検索", "カテゴリ表示"])
all_categories = sorted(df["category"].dropna().unique().tolist())

st.markdown('<div class="main-title">AI関連株コード辞典</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">AIを中心に、GPU・メモリー・冷却・電力・原子力・光通信・素材などを関連図で見る自分専用マップ</div>', unsafe_allow_html=True)

def stars(n):
    try:
        n = int(n)
    except Exception:
        n = 0
    return "★" * n + "☆" * (5 - n)

def stock_card(row):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    c1, c2 = st.columns([1.2, 2])

    with c1:
        st.markdown(f'<div class="ticker">{row["ticker"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="company">{row["company"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">{row["category"]}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">AI関連度 {stars(row["ai_score"])}</span>', unsafe_allow_html=True)

    with c2:
        st.write("**何を作るか / 事業内容**")
        st.write(row["business"])
        st.write("**AIとのつながり**")
        st.write(row["ai_relation"])
        st.write("**関連キーワード**")
        st.write(row["keywords"])

    st.markdown("</div>", unsafe_allow_html=True)

def metric_area(row):
    st.subheader("📊 株価・指標")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("株価", row["price"])
    c2.metric("PER", row["per"])
    c3.metric("PBR", row["pbr"])
    c4.metric("時価総額", row["market_cap"])

def related_table(row):
    st.subheader("🔗 関連銘柄")
    related = [x.strip().upper() for x in str(row["related"]).split(",") if x.strip()]
    related_df = df[df["ticker"].isin(related)]

    if len(related_df) == 0:
        st.info("関連銘柄はまだ登録されていません。")
        return

    st.dataframe(
        related_df[["ticker", "company", "category", "business", "ai_score"]],
        use_container_width=True,
        hide_index=True,
    )

def make_mindmap_html(selected_ticker=None):
    categories = [
        ("GPU", ["NVDA", "AMD"]),
        ("メモリー", ["MU", "000660"]),
        ("冷却", ["VRT", "TT", "JCI"]),
        ("電力", ["ETN", "HUBB", "PWR"]),
        ("原子力", ["CEG", "SMR"]),
        ("光通信", ["GLW", "LITE", "COHR"]),
        ("データセンター", ["EQIX", "DLR"]),
        ("半導体製造装置", ["ASML", "AMAT", "LRCX"]),
        ("素材", ["FCX", "SCCO", "ALB"]),
    ]

    blocks = []
    for cat, tickers in categories:
        items = []
        for t in tickers:
            hit = df[df["ticker"] == t]
            name = hit.iloc[0]["company"] if len(hit) else ""
            active = " active" if selected_ticker and t == selected_ticker.upper() else ""
            items.append(f'<div class="node stock{active}">{t}<br><small>{name}</small></div>')
        blocks.append(f'''
            <div class="branch">
                <div class="node category">{cat}</div>
                <div class="stocks">{''.join(items)}</div>
            </div>
        ''')

    html = f'''
    <html>
    <head>
    <style>
    body {{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#fafafa;margin:0;padding:12px;}}
    .map {{display:flex;gap:16px;align-items:stretch;overflow-x:auto;padding:12px;border:1px solid #e5e7eb;border-radius:18px;background:white;}}
    .center {{min-width:120px;display:flex;align-items:center;justify-content:center;}}
    .ai {{width:105px;height:105px;border-radius:24px;background:#111827;color:white;font-size:42px;font-weight:900;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px rgba(0,0,0,.18);}}
    .branches {{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:12px;min-width:740px;}}
    .branch {{border:1px solid #e5e7eb;border-radius:16px;padding:10px;background:#fff;}}
    .node.category {{font-weight:800;font-size:18px;border-bottom:3px solid #ff7ab6;display:inline-block;margin-bottom:8px;}}
    .stocks {{display:flex;flex-wrap:wrap;gap:8px;}}
    .node.stock {{border:1px solid #d1d5db;border-radius:12px;padding:8px 10px;min-width:78px;background:#f9fafb;font-weight:800;}}
    .node.stock small {{font-weight:500;color:#555;}}
    .node.stock.active {{background:#fff7d6;border:3px solid #f59e0b;}}
    </style>
    </head>
    <body>
      <div class="map">
        <div class="center"><div class="ai">AI</div></div>
        <div class="branches">
          {''.join(blocks)}
        </div>
      </div>
    </body>
    </html>
    '''
    return html

if mode == "ティッカー検索":
    ticker = st.text_input("ティッカーコードを入力", value="NVDA").strip().upper()
    hit = df[df["ticker"] == ticker]

    if len(hit) == 0:
        st.error("そのティッカーはまだ登録されていません。stocks.csv に追加してください。")
        st.dataframe(df[["ticker", "company", "category"]], use_container_width=True, hide_index=True)
    else:
        row = hit.iloc[0]
        stock_card(row)
        metric_area(row)
        st.subheader("🧠 AI関連図")
        components.html(make_mindmap_html(ticker), height=560, scrolling=True)
        related_table(row)

elif mode == "キーワード検索":
    keyword = st.text_input("キーワードを入力", value="冷却").strip()

    if keyword:
        mask = (
            df["ticker"].str.contains(keyword, case=False, na=False)
            | df["company"].str.contains(keyword, case=False, na=False)
            | df["category"].str.contains(keyword, case=False, na=False)
            | df["business"].str.contains(keyword, case=False, na=False)
            | df["ai_relation"].str.contains(keyword, case=False, na=False)
            | df["keywords"].str.contains(keyword, case=False, na=False)
        )
        result = df[mask]
        st.subheader(f"検索結果：{keyword}")

        if len(result) == 0:
            st.warning("該当する銘柄がありません。")
        else:
            st.dataframe(
                result[["ticker", "company", "category", "business", "ai_score", "price", "per", "pbr", "market_cap"]],
                use_container_width=True,
                hide_index=True,
            )

elif mode == "カテゴリ表示":
    category = st.selectbox("カテゴリを選択", all_categories)
    category_df = df[df["category"] == category].copy()
    st.subheader(f"📁 カテゴリ：{category}")
    st.dataframe(
        category_df[["ticker", "company", "category", "business", "ai_score", "price", "per", "pbr", "market_cap"]],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("🧠 AI関連図")
    components.html(make_mindmap_html(), height=560, scrolling=True)

st.markdown("---")
with st.expander("🛠 データの追加・修正方法"):
    st.markdown('''
    ### 銘柄を増やす方法
    `stocks.csv` に1行追加します。

    必要な列：
    `ticker, company, category, business, ai_relation, ai_score, price, per, pbr, market_cap, keywords, related`

    ### 注意
    今の株価・PER・PBR・時価総額はサンプル値です。  
    次の段階で `yfinance` などを使って自動取得にできます。
    ''')
