import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
import yfinance as yf

# ============================================================
# AI関連株コード辞典 v2
# 機能：
# - ティッカー検索
# - 会社カード表示
# - yfinanceで株価・PER・PBR・時価総額などを自動取得
# - 株価チャート表示
# - 関連銘柄一覧
# - AI関連図ハイライト
# ============================================================

st.set_page_config(
    page_title="AI関連株コード辞典 v2",
    page_icon="📈",
    layout="wide",
)

# -----------------------------
# データ読み込み
# -----------------------------
@st.cache_data
def load_data():
    path = Path(__file__).parent / "stocks.csv"
    df = pd.read_csv(path)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["yf_ticker"] = df["yf_ticker"].astype(str)
    df["keywords"] = df["keywords"].fillna("")
    df["related"] = df["related"].fillna("")
    return df

df = load_data()

# -----------------------------
# yfinance取得
# -----------------------------
@st.cache_data(ttl=1800)
def get_stock_info(yf_ticker):
    """
    30分キャッシュ。
    取得できないデータは None で返す。
    """
    try:
        t = yf.Ticker(yf_ticker)
        info = t.info or {}

        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )

        prev_close = info.get("previousClose")
        market_cap = info.get("marketCap")
        trailing_pe = info.get("trailingPE")
        forward_pe = info.get("forwardPE")
        price_to_book = info.get("priceToBook")
        fifty_two_high = info.get("fiftyTwoWeekHigh")
        fifty_two_low = info.get("fiftyTwoWeekLow")
        dividend_yield = info.get("dividendYield")

        change = None
        change_pct = None
        if price is not None and prev_close not in [None, 0]:
            change = price - prev_close
            change_pct = change / prev_close * 100

        return {
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "market_cap": market_cap,
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "price_to_book": price_to_book,
            "fifty_two_high": fifty_two_high,
            "fifty_two_low": fifty_two_low,
            "dividend_yield": dividend_yield,
            "currency": info.get("currency", ""),
            "long_name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
        }
    except Exception:
        return {
            "price": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
            "market_cap": None,
            "trailing_pe": None,
            "forward_pe": None,
            "price_to_book": None,
            "fifty_two_high": None,
            "fifty_two_low": None,
            "dividend_yield": None,
            "currency": "",
            "long_name": "",
            "sector": "",
            "industry": "",
        }

@st.cache_data(ttl=1800)
def get_history(yf_ticker, period):
    try:
        t = yf.Ticker(yf_ticker)
        hist = t.history(period=period)
        if hist is None or hist.empty:
            return pd.DataFrame()
        hist = hist.reset_index()
        return hist
    except Exception:
        return pd.DataFrame()

# -----------------------------
# 表示用関数
# -----------------------------
def stars(n):
    try:
        n = int(n)
    except Exception:
        n = 0
    return "★" * n + "☆" * (5 - n)

def fmt_num(x, decimals=2):
    if x is None or pd.isna(x):
        return "未取得"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)

def fmt_price(x, currency=""):
    if x is None or pd.isna(x):
        return "未取得"
    try:
        if currency:
            return f"{currency} {float(x):,.2f}"
        return f"{float(x):,.2f}"
    except Exception:
        return str(x)

def fmt_percent(x):
    if x is None or pd.isna(x):
        return "未取得"
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return str(x)

def fmt_market_cap(x):
    if x is None or pd.isna(x):
        return "未取得"
    try:
        x = float(x)
        if x >= 1_000_000_000_000:
            return f"{x / 1_000_000_000_000:.2f}T"
        if x >= 1_000_000_000:
            return f"{x / 1_000_000_000:.2f}B"
        if x >= 1_000_000:
            return f"{x / 1_000_000:.2f}M"
        return f"{x:,.0f}"
    except Exception:
        return str(x)

def safe_get(row, col, default=""):
    try:
        return row[col]
    except Exception:
        return default

# -----------------------------
# CSS
# -----------------------------
st.markdown(
    """
    <style>
    .main-title {
        font-size: 36px;
        font-weight: 900;
        margin-bottom: 4px;
        letter-spacing: -0.02em;
    }
    .sub-title {
        color: #64748b;
        font-size: 15px;
        margin-bottom: 20px;
    }
    .hero-card {
        background: linear-gradient(135deg, #111827 0%, #1f2937 60%, #374151 100%);
        color: white;
        border-radius: 22px;
        padding: 22px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.16);
        margin-bottom: 18px;
    }
    .hero-ticker {
        font-size: 42px;
        font-weight: 900;
        line-height: 1.0;
    }
    .hero-company {
        font-size: 22px;
        color: #e5e7eb;
        margin-top: 6px;
        margin-bottom: 12px;
    }
    .badge {
        display: inline-block;
        background: rgba(255,255,255,0.14);
        color: white;
        padding: 7px 11px;
        border-radius: 999px;
        margin: 4px 6px 4px 0;
        font-size: 13px;
        border: 1px solid rgba(255,255,255,0.18);
    }
    .white-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 4px 18px rgba(0,0,0,0.05);
        margin-bottom: 14px;
    }
    .small-label {
        color: #64748b;
        font-size: 13px;
        font-weight: 700;
    }
    .logic-note {
        background: #fff7d6;
        border-left: 5px solid #f59e0b;
        padding: 12px 14px;
        border-radius: 12px;
        margin-bottom: 12px;
    }
    .risk-note {
        background: #fff1f2;
        border-left: 5px solid #e11d48;
        padding: 12px 14px;
        border-radius: 12px;
        margin-bottom: 12px;
    }
    .stMetric {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        padding: 12px;
        border-radius: 16px;
        box-shadow: 0 3px 14px rgba(0,0,0,0.04);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# 関連図HTML
# -----------------------------
def make_mindmap_html(selected_ticker=None):
    categories = [
        ("GPU", ["NVDA", "AMD"]),
        ("メモリー", ["MU", "000660.KS"]),
        ("冷却", ["VRT", "TT", "JCI"]),
        ("電力", ["ETN", "HUBB", "PWR"]),
        ("原子力", ["CEG", "SMR"]),
        ("光通信", ["GLW", "LITE", "COHR"]),
        ("データセンター", ["EQIX", "DLR"]),
        ("半導体製造装置", ["ASML", "AMAT", "LRCX"]),
        ("素材", ["FCX", "SCCO", "ALB"]),
    ]

    selected = selected_ticker.upper() if selected_ticker else ""

    blocks = []
    for cat, tickers in categories:
        items = []
        for t in tickers:
            hit = df[(df["ticker"] == t) | (df["yf_ticker"].str.upper() == t)]
            if len(hit):
                row = hit.iloc[0]
                display_ticker = row["ticker"]
                name = row["company"]
            else:
                display_ticker = t
                name = ""

            active = " active" if selected in [display_ticker.upper(), t.upper()] else ""
            items.append(f'<div class="node stock{active}">{display_ticker}<br><small>{name}</small></div>')

        blocks.append(f"""
            <div class="branch">
                <div class="node category">{cat}</div>
                <div class="stocks">{''.join(items)}</div>
            </div>
        """)

    html = f"""
    <html>
    <head>
    <style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #fafafa;
        margin: 0;
        padding: 12px;
    }}
    .map {{
        display: flex;
        gap: 16px;
        align-items: stretch;
        overflow-x: auto;
        padding: 12px;
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        background: white;
    }}
    .center {{
        min-width: 125px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .ai {{
        width: 110px;
        height: 110px;
        border-radius: 28px;
        background: #111827;
        color: white;
        font-size: 44px;
        font-weight: 900;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 8px 22px rgba(0,0,0,.18);
    }}
    .branches {{
        display: grid;
        grid-template-columns: repeat(3, minmax(225px, 1fr));
        gap: 12px;
        min-width: 780px;
    }}
    .branch {{
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        padding: 10px;
        background: #fff;
    }}
    .node.category {{
        font-weight: 900;
        font-size: 18px;
        border-bottom: 3px solid #ff7ab6;
        display: inline-block;
        margin-bottom: 8px;
    }}
    .stocks {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }}
    .node.stock {{
        border: 1px solid #d1d5db;
        border-radius: 12px;
        padding: 8px 10px;
        min-width: 82px;
        background: #f9fafb;
        font-weight: 900;
        line-height: 1.15;
    }}
    .node.stock small {{
        font-weight: 500;
        color: #555;
        font-size: 11px;
    }}
    .node.stock.active {{
        background: #fff7d6;
        border: 3px solid #f59e0b;
        transform: scale(1.03);
    }}
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
    """
    return html

# -----------------------------
# ページタイトル
# -----------------------------
st.markdown('<div class="main-title">AI関連株コード辞典 v2</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">ティッカーを入力すると、会社情報・株価指標・チャート・関連銘柄・AI関連図を表示します。</div>',
    unsafe_allow_html=True,
)

# -----------------------------
# サイドバー
# -----------------------------
st.sidebar.title("🔎 操作メニュー")
mode = st.sidebar.radio("表示モード", ["ティッカー検索", "キーワード検索", "カテゴリ表示", "全銘柄一覧"])
st.sidebar.markdown("---")
st.sidebar.caption("例：NVDA / VRT / CEG / GLW / FCX / 000660.KS")
st.sidebar.caption("※ 自動取得は yfinance を使います。取得できない項目は「未取得」と表示します。")

period_label = st.sidebar.selectbox(
    "チャート期間",
    ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"],
    index=2,
)

period_map = {
    "1ヶ月": "1mo",
    "3ヶ月": "3mo",
    "6ヶ月": "6mo",
    "1年": "1y",
    "5年": "5y",
}

# -----------------------------
# 表示ブロック
# -----------------------------
def show_stock_page(row):
    yf_ticker = row["yf_ticker"]
    info = get_stock_info(yf_ticker)

    # ヒーローカード
    st.markdown('<div class="hero-card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1.2, 2])

    with col1:
        st.markdown(f'<div class="hero-ticker">{row["ticker"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-company">{row["company"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">{row["category"]}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">AI関連度 {stars(row["ai_score"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">yfinance: {yf_ticker}</span>', unsafe_allow_html=True)

    with col2:
        st.write("**何を作るか / 事業内容**")
        st.write(row["business"])
        st.write("**AIとのつながり**")
        st.write(row["ai_relation"])
        if info.get("sector") or info.get("industry"):
            st.write("**Yahoo Finance分類**")
            st.write(f'{info.get("sector", "")} / {info.get("industry", "")}')

    st.markdown("</div>", unsafe_allow_html=True)

    # 指標
    st.subheader("📊 自動取得データ")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("株価", fmt_price(info["price"], info["currency"]), fmt_percent(info["change_pct"]))
    c2.metric("時価総額", fmt_market_cap(info["market_cap"]))
    c3.metric("PER", fmt_num(info["trailing_pe"]))
    c4.metric("予想PER", fmt_num(info["forward_pe"]))
    c5.metric("PBR", fmt_num(info["price_to_book"]))

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("前日終値", fmt_price(info["prev_close"], info["currency"]))
    c7.metric("52週高値", fmt_price(info["fifty_two_high"], info["currency"]))
    c8.metric("52週安値", fmt_price(info["fifty_two_low"], info["currency"]))
    if info["dividend_yield"] is not None:
        dy = info["dividend_yield"] * 100
    else:
        dy = None
    c9.metric("配当利回り", fmt_percent(dy))

    st.caption("※ 株価・指標はyfinance経由の参考データです。取得できない項目や遅延がある場合があります。投資判断は自己責任でお願いします。")

    # チャート
    st.subheader("📈 株価チャート")
    hist = get_history(yf_ticker, period_map[period_label])

    if hist.empty:
        st.warning("チャートデータを取得できませんでした。")
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=hist["Date"],
                y=hist["Close"],
                mode="lines",
                name="Close",
            )
        )
        fig.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=30, b=20),
            xaxis_title="Date",
            yaxis_title="Close",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

    # 見るポイント
    st.subheader("🧠 見るポイント")
    p1, p2 = st.columns(2)
    with p1:
        st.markdown(
            f"""
            <div class="logic-note">
            <b>関連ロジック</b><br>
            {row["ai_relation"]}<br><br>
            <b>関連キーワード：</b>{row["keywords"]}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with p2:
        st.markdown(
            """
            <div class="risk-note">
            <b>チェック項目</b><br>
            □ 決算・ガイダンス<br>
            □ 受注・バックログ<br>
            □ データセンター投資動向<br>
            □ 金利・為替・地政学リスク<br>
            □ PER/PBRが高すぎないか
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 関連図
    st.subheader("🗺 AI関連図")
    components.html(make_mindmap_html(row["ticker"]), height=560, scrolling=True)

    # 関連銘柄
    st.subheader("🔗 関連銘柄")
    related = [x.strip().upper() for x in str(row["related"]).split(",") if x.strip()]
    related_df = df[
        df["ticker"].str.upper().isin(related)
        | df["yf_ticker"].str.upper().isin(related)
    ]

    if related_df.empty:
        st.info("関連銘柄はまだ登録されていません。")
    else:
        st.dataframe(
            related_df[["ticker", "company", "category", "business", "ai_score", "yf_ticker"]],
            use_container_width=True,
            hide_index=True,
        )

# -----------------------------
# メイン処理
# -----------------------------
if mode == "ティッカー検索":
    default = "NVDA"
    ticker = st.text_input("ティッカーコードを入力", value=default).strip().upper()

    hit = df[
        (df["ticker"].str.upper() == ticker)
        | (df["yf_ticker"].str.upper() == ticker)
    ]

    if hit.empty:
        st.error("そのティッカーはまだ登録されていません。stocks.csv に追加してください。")
        st.dataframe(df[["ticker", "yf_ticker", "company", "category"]], use_container_width=True, hide_index=True)
    else:
        show_stock_page(hit.iloc[0])

elif mode == "キーワード検索":
    keyword = st.text_input("キーワードを入力", value="冷却").strip()

    if keyword:
        mask = (
            df["ticker"].str.contains(keyword, case=False, na=False)
            | df["yf_ticker"].str.contains(keyword, case=False, na=False)
            | df["company"].str.contains(keyword, case=False, na=False)
            | df["category"].str.contains(keyword, case=False, na=False)
            | df["business"].str.contains(keyword, case=False, na=False)
            | df["ai_relation"].str.contains(keyword, case=False, na=False)
            | df["keywords"].str.contains(keyword, case=False, na=False)
        )
        result = df[mask]

        st.subheader(f"検索結果：{keyword}")
        if result.empty:
            st.warning("該当する銘柄がありません。")
        else:
            st.dataframe(
                result[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "keywords"]],
                use_container_width=True,
                hide_index=True,
            )

elif mode == "カテゴリ表示":
    categories = sorted(df["category"].dropna().unique().tolist())
    category = st.selectbox("カテゴリを選択", categories)
    category_df = df[df["category"] == category].copy()

    st.subheader(f"📁 カテゴリ：{category}")
    st.dataframe(
        category_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "keywords"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("🗺 AI関連図")
    components.html(make_mindmap_html(), height=560, scrolling=True)

elif mode == "全銘柄一覧":
    st.subheader("📚 登録銘柄一覧")
    st.dataframe(
        df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "related"]],
        use_container_width=True,
        hide_index=True,
    )

# -----------------------------
# 編集方法
# -----------------------------
st.markdown("---")
with st.expander("🛠 銘柄データの追加・修正方法"):
    st.markdown(
        """
        ### 銘柄を増やす場所
        `stocks.csv` に1行追加します。

        ### 大事な列
        - `ticker`：サイト内で表示するティッカー
        - `yf_ticker`：yfinanceで取得するティッカー
        - `company`：会社名
        - `category`：GPU、冷却、電力など
        - `business`：何を作るか
        - `ai_relation`：AIとどう関係するか
        - `ai_score`：1〜5
        - `keywords`：検索用キーワード
        - `related`：関連銘柄をスペース区切りで入れる

        ### 日本株の例
        yfinanceでは日本株は `7203.T` のように `.T` を付けることが多いです。

        ### 韓国株の例
        SK hynixは `000660.KS` のように `.KS` を付けます。
        """
    )
