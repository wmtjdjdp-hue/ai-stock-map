import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
from urllib.parse import quote_plus
import yfinance as yf

st.set_page_config(page_title="AI関連株コード辞典 v3", page_icon="📈", layout="wide")

@st.cache_data
def load_data():
    path = Path(__file__).parent / "stocks.csv"
    df = pd.read_csv(path)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["yf_ticker"] = df["yf_ticker"].astype(str).str.upper()
    df["keywords"] = df["keywords"].fillna("")
    df["related"] = df["related"].fillna("")
    df["official_ir_url"] = df["official_ir_url"].fillna("")
    return df

df = load_data()

@st.cache_data(ttl=1800)
def get_history(yf_ticker, period):
    try:
        hist = yf.Ticker(yf_ticker).history(period=period)
        if hist is None or hist.empty:
            return pd.DataFrame()
        return hist.reset_index()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def get_stock_info(yf_ticker):
    result = {
        "price": None,
        "prev_close": None,
        "change_pct": None,
        "market_cap": None,
        "trailing_pe": None,
        "forward_pe": None,
        "price_to_book": None,
        "fifty_two_high": None,
        "fifty_two_low": None,
        "dividend_yield": None,
        "currency": "",
        "sector": "",
        "industry": "",
    }

    try:
        t = yf.Ticker(yf_ticker)

        try:
            fast = t.fast_info
            result["price"] = getattr(fast, "last_price", None) or fast.get("last_price")
            result["prev_close"] = getattr(fast, "previous_close", None) or fast.get("previous_close")
            result["market_cap"] = getattr(fast, "market_cap", None) or fast.get("market_cap")
            result["currency"] = getattr(fast, "currency", "") or fast.get("currency", "")
        except Exception:
            pass

        try:
            info = t.info or {}
            result["price"] = result["price"] or info.get("currentPrice") or info.get("regularMarketPrice")
            result["prev_close"] = result["prev_close"] or info.get("previousClose")
            result["market_cap"] = result["market_cap"] or info.get("marketCap")
            result["trailing_pe"] = info.get("trailingPE")
            result["forward_pe"] = info.get("forwardPE")
            result["price_to_book"] = info.get("priceToBook")
            result["fifty_two_high"] = info.get("fiftyTwoWeekHigh")
            result["fifty_two_low"] = info.get("fiftyTwoWeekLow")
            result["dividend_yield"] = info.get("dividendYield")
            result["currency"] = result["currency"] or info.get("currency", "")
            result["sector"] = info.get("sector", "")
            result["industry"] = info.get("industry", "")
        except Exception:
            pass

        if result["price"] is None or result["prev_close"] is None:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                closes = hist["Close"].dropna().tolist()
                if len(closes) >= 1 and result["price"] is None:
                    result["price"] = closes[-1]
                if len(closes) >= 2 and result["prev_close"] is None:
                    result["prev_close"] = closes[-2]

        if result["price"] is not None and result["prev_close"] not in [None, 0]:
            result["change_pct"] = (float(result["price"]) - float(result["prev_close"])) / float(result["prev_close"]) * 100

    except Exception:
        pass

    return result

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

def jp_code(yf_ticker):
    t = str(yf_ticker).upper().strip()
    if t.endswith(".T"):
        return t.replace(".T", "")
    if t.endswith(".JP"):
        return t.replace(".JP", "")
    if len(t) == 4 and t.isdigit():
        return t
    return ""

def make_external_links(row):
    ticker = str(row["ticker"]).upper().strip()
    yf_ticker = str(row["yf_ticker"]).upper().strip()
    company = str(row["company"]).strip()
    code = jp_code(yf_ticker)
    q = quote_plus(f"{ticker} {company}")

    links = []

    links.append(("Yahoo Finance", f"https://finance.yahoo.com/quote/{yf_ticker}"))
    links.append(("TradingView", f"https://www.tradingview.com/symbols/{yf_ticker.replace('.', '-')}/"))
    links.append(("Google検索", f"https://www.google.com/search?q={q}+stock"))

    if code:
        links.append(("株探", f"https://kabutan.jp/stock/?code={code}"))
        links.append(("株探チャート", f"https://kabutan.jp/stock/chart?code={code}"))
        links.append(("四季報オンライン", f"https://shikiho.toyokeizai.net/stocks/{code}"))
        links.append(("バフェットコード", f"https://www.buffett-code.com/company/{code}/"))
        links.append(("バフェットコード財務", f"https://www.buffett-code.com/company/{code}/financial"))
        links.append(("IR BANK", f"https://irbank.net/{code}"))
    else:
        links.append(("株探で検索", f"https://www.google.com/search?q={quote_plus(ticker + ' 株探')}"))
        links.append(("四季報で検索", f"https://www.google.com/search?q={quote_plus(ticker + ' 四季報')}"))
        links.append(("バフェットコードで検索", f"https://www.google.com/search?q={quote_plus(ticker + ' バフェットコード')}"))

    if str(row.get("official_ir_url", "")).strip():
        links.append(("公式IR", str(row["official_ir_url"]).strip()))
    else:
        links.append(("公式IRを検索", f"https://www.google.com/search?q={quote_plus(company + ' investor relations IR')}"))

    return links

st.markdown(
    """
    <style>
    .main-title {font-size:36px;font-weight:900;margin-bottom:4px;}
    .sub-title {color:#64748b;font-size:15px;margin-bottom:20px;}
    .hero-card {background:linear-gradient(135deg,#111827,#374151);color:white;border-radius:22px;padding:22px;box-shadow:0 8px 24px rgba(0,0,0,.16);margin-bottom:18px;}
    .hero-ticker {font-size:42px;font-weight:900;line-height:1.0;}
    .hero-company {font-size:22px;color:#e5e7eb;margin-top:6px;margin-bottom:12px;}
    .badge {display:inline-block;background:rgba(255,255,255,.14);color:white;padding:7px 11px;border-radius:999px;margin:4px 6px 4px 0;font-size:13px;border:1px solid rgba(255,255,255,.18);}
    .link-card {background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:14px;margin-bottom:12px;}
    .notice {background:#fff7d6;border-left:5px solid #f59e0b;padding:12px 14px;border-radius:12px;margin-bottom:12px;}
    .risk {background:#fff1f2;border-left:5px solid #e11d48;padding:12px 14px;border-radius:12px;margin-bottom:12px;}
    .stMetric {background:#fff;border:1px solid #e5e7eb;padding:12px;border-radius:16px;box-shadow:0 3px 14px rgba(0,0,0,.04);}
    </style>
    """,
    unsafe_allow_html=True,
)

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
        ("日本AI関連", ["7203.T", "9984.T", "6857.T"]),
    ]
    selected = selected_ticker.upper() if selected_ticker else ""
    blocks = []
    for cat, tickers in categories:
        items = []
        for t in tickers:
            hit = df[(df["ticker"] == t) | (df["yf_ticker"] == t)]
            if len(hit):
                row = hit.iloc[0]
                display_ticker = row["ticker"]
                name = row["company"]
            else:
                display_ticker = t
                name = ""
            active = " active" if selected in [display_ticker.upper(), t.upper()] else ""
            items.append(f'<div class="node stock{active}">{display_ticker}<br><small>{name}</small></div>')
        blocks.append(f"<div class='branch'><div class='node category'>{cat}</div><div class='stocks'>{''.join(items)}</div></div>")

    html = f"""
    <html><head><style>
    body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fafafa;margin:0;padding:12px;}}
    .map {{display:flex;gap:16px;align-items:stretch;overflow-x:auto;padding:12px;border:1px solid #e5e7eb;border-radius:18px;background:white;}}
    .center {{min-width:125px;display:flex;align-items:center;justify-content:center;}}
    .ai {{width:110px;height:110px;border-radius:28px;background:#111827;color:white;font-size:44px;font-weight:900;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px rgba(0,0,0,.18);}}
    .branches {{display:grid;grid-template-columns:repeat(3,minmax(225px,1fr));gap:12px;min-width:780px;}}
    .branch {{border:1px solid #e5e7eb;border-radius:16px;padding:10px;background:#fff;}}
    .node.category {{font-weight:900;font-size:18px;border-bottom:3px solid #ff7ab6;display:inline-block;margin-bottom:8px;}}
    .stocks {{display:flex;flex-wrap:wrap;gap:8px;}}
    .node.stock {{border:1px solid #d1d5db;border-radius:12px;padding:8px 10px;min-width:82px;background:#f9fafb;font-weight:900;line-height:1.15;}}
    .node.stock small {{font-weight:500;color:#555;font-size:11px;}}
    .node.stock.active {{background:#fff7d6;border:3px solid #f59e0b;transform:scale(1.03);}}
    </style></head><body>
    <div class="map"><div class="center"><div class="ai">AI</div></div><div class="branches">{''.join(blocks)}</div></div>
    </body></html>
    """
    return html

def show_external_links(row):
    st.subheader("🔎 外部調査リンク")
    st.markdown(
        """
        <div class="notice">
        <b>このエリアは外部サイトへのリンクだけを作ります。</b><br>
        四季報・株探・バフェットコード等の中身をコピー表示せず、各サイトで確認するためのボタンです。
        </div>
        """,
        unsafe_allow_html=True,
    )
    links = make_external_links(row)
    cols = st.columns(3)
    for i, (label, url) in enumerate(links):
        with cols[i % 3]:
            st.link_button(label, url, use_container_width=True)

def show_stock_page(row):
    info = get_stock_info(row["yf_ticker"])

    st.markdown('<div class="hero-card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1.1, 2])
    with col1:
        st.markdown(f'<div class="hero-ticker">{row["ticker"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-company">{row["company"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">{row["category"]}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">AI関連度 {stars(row["ai_score"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">取得コード {row["yf_ticker"]}</span>', unsafe_allow_html=True)
    with col2:
        st.write("**何を作るか / 事業内容**")
        st.write(row["business"])
        st.write("**AIとのつながり**")
        st.write(row["ai_relation"])
        if info.get("sector") or info.get("industry"):
            st.write("**分類**")
            st.write(f'{info.get("sector","")} / {info.get("industry","")}')
    st.markdown("</div>", unsafe_allow_html=True)

    show_external_links(row)

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
    dy = info["dividend_yield"] * 100 if info["dividend_yield"] is not None else None
    c9.metric("配当利回り", fmt_percent(dy))
    st.caption("※ 自動取得データはyfinance経由の参考値です。取得できない項目や遅延がある場合があります。")

    st.subheader("📈 株価チャート")
    hist = get_history(row["yf_ticker"], period_map[period_label])
    if hist.empty:
        st.warning("チャートデータを取得できませんでした。")
    else:
        date_col = "Date" if "Date" in hist.columns else hist.columns[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist[date_col], y=hist["Close"], mode="lines", name="Close"))
        fig.update_layout(height=380, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("🗺 AI関連図")
    components.html(make_mindmap_html(row["ticker"]), height=560, scrolling=True)

    st.subheader("🔗 関連銘柄")
    related = [x.strip().upper() for x in str(row["related"]).split(",") if x.strip()]
    related_df = df[df["ticker"].isin(related) | df["yf_ticker"].isin(related)]
    if related_df.empty:
        st.info("関連銘柄はまだ登録されていません。")
    else:
        st.dataframe(related_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

st.markdown('<div class="main-title">AI関連株コード辞典 v3</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">ティッカー入力で、会社情報・自動取得データ・チャート・関連図・外部調査リンクを表示します。</div>', unsafe_allow_html=True)

st.sidebar.title("🔎 操作メニュー")
mode = st.sidebar.radio("表示モード", ["ティッカー検索", "キーワード検索", "カテゴリ表示", "全銘柄一覧"])
period_label = st.sidebar.selectbox("チャート期間", ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"], index=2)
period_map = {"1ヶ月": "1mo", "3ヶ月": "3mo", "6ヶ月": "6mo", "1年": "1y", "5年": "5y"}

st.sidebar.markdown("---")
st.sidebar.caption("日本株例：7203.T / 9984.T / 6857.T")
st.sidebar.caption("米国株例：NVDA / VRT / CEG")

if mode == "ティッカー検索":
    ticker = st.text_input("ティッカーコードを入力", value="NVDA").strip().upper()
    hit = df[(df["ticker"] == ticker) | (df["yf_ticker"] == ticker)]
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
            st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

elif mode == "カテゴリ表示":
    category = st.selectbox("カテゴリを選択", sorted(df["category"].dropna().unique().tolist()))
    result = df[df["category"] == category]
    st.subheader(f"カテゴリ：{category}")
    st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)
    components.html(make_mindmap_html(), height=560, scrolling=True)

else:
    st.subheader("登録銘柄一覧")
    st.dataframe(df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "official_ir_url"]], use_container_width=True, hide_index=True)

st.markdown("---")
with st.expander("🛠 銘柄データの追加・修正方法"):
    st.markdown("""
    `stocks.csv` に1行追加します。

    大事な列：
    - `ticker`：表示用ティッカー
    - `yf_ticker`：yfinance取得用コード。日本株は例：`7203.T`
    - `official_ir_url`：公式IRページURL。空欄でもOK
    - `related`：関連銘柄。カンマ区切り
    """)
