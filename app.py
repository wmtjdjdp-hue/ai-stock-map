
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
from urllib.parse import quote_plus
import requests
import yfinance as yf

st.set_page_config(page_title="AI関連株コード辞典 v4", page_icon="📈", layout="wide")

# ============================================================
# AI関連株コード辞典 v4
# 目的：
# yfinanceを中心に、Alpha Vantage / FMP の無料APIを補助として使う構造
#
# 優先順位：
# 1. yfinance
# 2. FMP_API_KEY があれば Financial Modeling Prep
# 3. ALPHAVANTAGE_API_KEY があれば Alpha Vantage
# 4. 取れなければ「未取得」
#
# Streamlit Cloud の Secrets に入れる例：
# FMP_API_KEY = "あなたのFMPキー"
# ALPHAVANTAGE_API_KEY = "あなたのAlpha Vantageキー"
# ============================================================

# -----------------------------
# データ読み込み
# -----------------------------
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

# -----------------------------
# Secrets
# -----------------------------
def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""

FMP_API_KEY = get_secret("FMP_API_KEY")
ALPHAVANTAGE_API_KEY = get_secret("ALPHAVANTAGE_API_KEY")

# -----------------------------
# 共通フォーマット
# -----------------------------
def stars(n):
    try:
        n = int(n)
    except Exception:
        n = 0
    return "★" * n + "☆" * (5 - n)

def fmt_num(x, decimals=2):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)

def fmt_price(x, currency=""):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        prefix = f"{currency} " if currency else ""
        return f"{prefix}{float(x):,.2f}"
    except Exception:
        return str(x)

def fmt_percent(x):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return str(x)

def fmt_market_cap(x):
    if x is None or x == "" or pd.isna(x):
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

def pick_first(*values):
    for v in values:
        if v is not None and v != "" and not (isinstance(v, float) and pd.isna(v)):
            return v
    return None

def is_us_like_ticker(ticker):
    t = str(ticker).upper()
    return "." not in t and t.isalpha()

def to_alpha_symbol(yf_ticker):
    # Alpha Vantage/FMP用。日本株や韓国株はまず対象外扱い。
    t = str(yf_ticker).upper().strip()
    if "." in t:
        return ""
    return t

def jp_code(yf_ticker):
    t = str(yf_ticker).upper().strip()
    if t.endswith(".T"):
        return t.replace(".T", "")
    if t.endswith(".JP"):
        return t.replace(".JP", "")
    if len(t) == 4 and t.isdigit():
        return t
    return ""

# -----------------------------
# yfinance
# -----------------------------
@st.cache_data(ttl=1800)
def get_yf_history(yf_ticker, period):
    try:
        hist = yf.Ticker(yf_ticker).history(period=period)
        if hist is None or hist.empty:
            return pd.DataFrame()
        return hist.reset_index()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def get_yfinance_data(yf_ticker):
    result = {
        "source": "yfinance",
        "price": None,
        "prev_close": None,
        "change_pct": None,
        "market_cap": None,
        "per": None,
        "forward_pe": None,
        "pbr": None,
        "forward_pbr": None,
        "fifty_two_high": None,
        "fifty_two_low": None,
        "dividend_yield": None,
        "currency": "",
        "sector": "",
        "industry": "",
    }

    try:
        t = yf.Ticker(yf_ticker)

        # fast_info
        try:
            fast = t.fast_info
            result["price"] = getattr(fast, "last_price", None) or fast.get("last_price")
            result["prev_close"] = getattr(fast, "previous_close", None) or fast.get("previous_close")
            result["market_cap"] = getattr(fast, "market_cap", None) or fast.get("market_cap")
            result["currency"] = getattr(fast, "currency", "") or fast.get("currency", "")
        except Exception:
            pass

        # info
        try:
            info = t.info or {}
            result["price"] = pick_first(result["price"], info.get("currentPrice"), info.get("regularMarketPrice"))
            result["prev_close"] = pick_first(result["prev_close"], info.get("previousClose"))
            result["market_cap"] = pick_first(result["market_cap"], info.get("marketCap"))
            result["per"] = pick_first(info.get("trailingPE"))
            result["forward_pe"] = pick_first(info.get("forwardPE"))
            result["pbr"] = pick_first(info.get("priceToBook"))
            result["fifty_two_high"] = pick_first(info.get("fiftyTwoWeekHigh"))
            result["fifty_two_low"] = pick_first(info.get("fiftyTwoWeekLow"))
            result["dividend_yield"] = pick_first(info.get("dividendYield"))
            result["currency"] = pick_first(result["currency"], info.get("currency"), "")
            result["sector"] = pick_first(info.get("sector"), "")
            result["industry"] = pick_first(info.get("industry"), "")
        except Exception:
            pass

        # history backup
        if result["price"] is None or result["prev_close"] is None:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                closes = hist["Close"].dropna().tolist()
                if len(closes) >= 1:
                    result["price"] = pick_first(result["price"], closes[-1])
                if len(closes) >= 2:
                    result["prev_close"] = pick_first(result["prev_close"], closes[-2])

        if result["price"] is not None and result["prev_close"] not in [None, 0]:
            result["change_pct"] = (float(result["price"]) - float(result["prev_close"])) / float(result["prev_close"]) * 100

    except Exception:
        pass

    return result

# -----------------------------
# Financial Modeling Prep
# -----------------------------
@st.cache_data(ttl=3600)
def get_fmp_data(symbol, api_key):
    result = {
        "source": "FMP",
        "price": None,
        "prev_close": None,
        "change_pct": None,
        "market_cap": None,
        "per": None,
        "forward_pe": None,
        "pbr": None,
        "forward_pbr": None,
        "fifty_two_high": None,
        "fifty_two_low": None,
        "dividend_yield": None,
        "currency": "USD",
        "sector": "",
        "industry": "",
    }

    if not api_key or not symbol:
        return result

    try:
        # profile endpoint
        url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={api_key}"
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                p = data[0]
                result["price"] = pick_first(p.get("price"))
                result["market_cap"] = pick_first(p.get("mktCap"))
                result["currency"] = pick_first(p.get("currency"), "USD")
                result["sector"] = pick_first(p.get("sector"), "")
                result["industry"] = pick_first(p.get("industry"), "")
                result["fifty_two_high"] = pick_first(p.get("range", "").split("-")[-1].strip() if isinstance(p.get("range"), str) and "-" in p.get("range") else None)
                result["fifty_two_low"] = pick_first(p.get("range", "").split("-")[0].strip() if isinstance(p.get("range"), str) and "-" in p.get("range") else None)

        # ratios ttm endpoint
        url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{symbol}?apikey={api_key}"
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                rr = data[0]
                result["per"] = pick_first(rr.get("peRatioTTM"))
                result["pbr"] = pick_first(rr.get("priceToBookRatioTTM"))
                dy = pick_first(rr.get("dividendYielTTM"), rr.get("dividendYieldTTM"))
                result["dividend_yield"] = dy

        # quote endpoint
        url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={api_key}"
        r = requests.get(url, timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                q = data[0]
                result["price"] = pick_first(result["price"], q.get("price"))
                result["prev_close"] = pick_first(q.get("previousClose"))
                result["change_pct"] = pick_first(q.get("changesPercentage"))
                result["market_cap"] = pick_first(result["market_cap"], q.get("marketCap"))
                result["per"] = pick_first(result["per"], q.get("pe"))
                result["fifty_two_high"] = pick_first(result["fifty_two_high"], q.get("yearHigh"))
                result["fifty_two_low"] = pick_first(result["fifty_two_low"], q.get("yearLow"))

    except Exception:
        pass

    return result

# -----------------------------
# Alpha Vantage
# -----------------------------
@st.cache_data(ttl=3600)
def get_alpha_data(symbol, api_key):
    result = {
        "source": "Alpha Vantage",
        "price": None,
        "prev_close": None,
        "change_pct": None,
        "market_cap": None,
        "per": None,
        "forward_pe": None,
        "pbr": None,
        "forward_pbr": None,
        "fifty_two_high": None,
        "fifty_two_low": None,
        "dividend_yield": None,
        "currency": "USD",
        "sector": "",
        "industry": "",
    }

    if not api_key or not symbol:
        return result

    try:
        # GLOBAL_QUOTE
        url = "https://www.alphavantage.co/query"
        params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            data = r.json().get("Global Quote", {})
            result["price"] = pick_first(data.get("05. price"))
            result["prev_close"] = pick_first(data.get("08. previous close"))
            result["change_pct"] = pick_first(str(data.get("10. change percent", "")).replace("%", ""))

        # OVERVIEW
        params = {"function": "OVERVIEW", "symbol": symbol, "apikey": api_key}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            data = r.json()
            result["market_cap"] = pick_first(data.get("MarketCapitalization"))
            result["per"] = pick_first(data.get("PERatio"))
            result["forward_pe"] = pick_first(data.get("ForwardPE"))
            result["pbr"] = pick_first(data.get("PriceToBookRatio"))
            result["fifty_two_high"] = pick_first(data.get("52WeekHigh"))
            result["fifty_two_low"] = pick_first(data.get("52WeekLow"))
            result["dividend_yield"] = pick_first(data.get("DividendYield"))
            result["sector"] = pick_first(data.get("Sector"), "")
            result["industry"] = pick_first(data.get("Industry"), "")

    except Exception:
        pass

    return result

# -----------------------------
# 複数データ源を合成
# -----------------------------
@st.cache_data(ttl=1800)
def get_combined_data(yf_ticker, fmp_key, alpha_key):
    yf_data = get_yfinance_data(yf_ticker)

    symbol = to_alpha_symbol(yf_ticker)
    fmp_data = get_fmp_data(symbol, fmp_key) if symbol else {}
    alpha_data = get_alpha_data(symbol, alpha_key) if symbol else {}

    result = {}
    source_map = {}

    keys = [
        "price", "prev_close", "change_pct", "market_cap",
        "per", "forward_pe", "pbr", "forward_pbr",
        "fifty_two_high", "fifty_two_low", "dividend_yield",
        "currency", "sector", "industry"
    ]

    # 優先順位は yfinance -> FMP -> Alpha Vantage
    for k in keys:
        candidates = [
            ("yfinance", yf_data.get(k)),
            ("FMP", fmp_data.get(k) if fmp_data else None),
            ("Alpha Vantage", alpha_data.get(k) if alpha_data else None),
        ]
        value = None
        src = ""
        for name, v in candidates:
            if v is not None and v != "" and not (isinstance(v, float) and pd.isna(v)):
                value = v
                src = name
                break
        result[k] = value
        source_map[k] = src if value is not None and value != "" else "未取得"

    return result, source_map, yf_data, fmp_data, alpha_data

# -----------------------------
# 外部リンク
# -----------------------------
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

# -----------------------------
# CSS
# -----------------------------
st.markdown(
    """
    <style>
    .main-title {font-size:36px;font-weight:900;margin-bottom:4px;}
    .sub-title {color:#64748b;font-size:15px;margin-bottom:20px;}
    .hero-card {background:linear-gradient(135deg,#111827,#374151);color:white;border-radius:22px;padding:22px;box-shadow:0 8px 24px rgba(0,0,0,.16);margin-bottom:18px;}
    .hero-ticker {font-size:42px;font-weight:900;line-height:1.0;}
    .hero-company {font-size:22px;color:#e5e7eb;margin-top:6px;margin-bottom:12px;}
    .badge {display:inline-block;background:rgba(255,255,255,.14);color:white;padding:7px 11px;border-radius:999px;margin:4px 6px 4px 0;font-size:13px;border:1px solid rgba(255,255,255,.18);}
    .notice {background:#fff7d6;border-left:5px solid #f59e0b;padding:12px 14px;border-radius:12px;margin-bottom:12px;}
    .safe {background:#ecfdf5;border-left:5px solid #10b981;padding:12px 14px;border-radius:12px;margin-bottom:12px;}
    .risk {background:#fff1f2;border-left:5px solid #e11d48;padding:12px 14px;border-radius:12px;margin-bottom:12px;}
    .stMetric {background:#fff;border:1px solid #e5e7eb;padding:12px;border-radius:16px;box-shadow:0 3px 14px rgba(0,0,0,.04);}
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# 関連図
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

# -----------------------------
# 表示
# -----------------------------
period_map = {"1ヶ月": "1mo", "3ヶ月": "3mo", "6ヶ月": "6mo", "1年": "1y", "5年": "5y"}

def show_external_links(row):
    st.subheader("🔎 外部調査リンク")
    st.markdown(
        """
        <div class="notice">
        <b>外部サイトの中身はコピーせず、リンクボタンだけを作ります。</b><br>
        四季報・株探・バフェットコード等は、各サイトで直接確認するためのボタンです。
        </div>
        """,
        unsafe_allow_html=True,
    )
    links = make_external_links(row)
    cols = st.columns(3)
    for i, (label, url) in enumerate(links):
        with cols[i % 3]:
            st.link_button(label, url, use_container_width=True)

def show_source_table(source_map):
    st.caption("各項目の取得元")
    rows = []
    for label, key in [
        ("株価", "price"),
        ("前日終値", "prev_close"),
        ("前日比", "change_pct"),
        ("時価総額", "market_cap"),
        ("PER", "per"),
        ("予想PER", "forward_pe"),
        ("PBR", "pbr"),
        ("予想PBR", "forward_pbr"),
        ("52週高値", "fifty_two_high"),
        ("52週安値", "fifty_two_low"),
        ("配当利回り", "dividend_yield"),
    ]:
        rows.append({"項目": label, "取得元": source_map.get(key, "未取得")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def show_stock_page(row):
    combined, source_map, yf_data, fmp_data, alpha_data = get_combined_data(row["yf_ticker"], FMP_API_KEY, ALPHAVANTAGE_API_KEY)

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
        if combined.get("sector") or combined.get("industry"):
            st.write("**分類**")
            st.write(f'{combined.get("sector","")} / {combined.get("industry","")}')
    st.markdown("</div>", unsafe_allow_html=True)

    show_external_links(row)

    st.subheader("📊 自動取得データ：複数ソース補完")
    if not FMP_API_KEY and not ALPHAVANTAGE_API_KEY:
        st.markdown(
            """
            <div class="notice">
            現在は <b>yfinanceのみ</b> で取得しています。<br>
            FMP_API_KEY または ALPHAVANTAGE_API_KEY を Streamlit Secrets に入れると、PER/PBR/時価総額の補完ができます。
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        active = []
        if FMP_API_KEY:
            active.append("FMP")
        if ALPHAVANTAGE_API_KEY:
            active.append("Alpha Vantage")
        st.markdown(
            f"""
            <div class="safe">
            補助APIが有効です：<b>{", ".join(active)}</b><br>
            yfinanceで取れない項目をAPIで補完します。
            </div>
            """,
            unsafe_allow_html=True,
        )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("株価", fmt_price(combined["price"], combined["currency"]), fmt_percent(combined["change_pct"]))
    c2.metric("時価総額", fmt_market_cap(combined["market_cap"]))
    c3.metric("PER", fmt_num(combined["per"]))
    c4.metric("予想PER", fmt_num(combined["forward_pe"]))
    c5.metric("PBR", fmt_num(combined["pbr"]))

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("前日終値", fmt_price(combined["prev_close"], combined["currency"]))
    c7.metric("52週高値", fmt_price(combined["fifty_two_high"], combined["currency"]))
    c8.metric("52週安値", fmt_price(combined["fifty_two_low"], combined["currency"]))
    dy = None
    if combined["dividend_yield"] is not None:
        try:
            dy = float(combined["dividend_yield"]) * 100 if float(combined["dividend_yield"]) < 1 else float(combined["dividend_yield"])
        except Exception:
            dy = combined["dividend_yield"]
    c9.metric("配当利回り", fmt_percent(dy))

    c10, c11 = st.columns(2)
    c10.metric("予想PBR", fmt_num(combined["forward_pbr"]))
    c11.metric("データ取得コード", row["yf_ticker"])

    with st.expander("📌 取得元を確認する"):
        show_source_table(source_map)

    st.caption("※ 自動取得データは参考値です。無料APIやyfinanceは欠損・遅延・制限があります。投資判断は自己責任でお願いします。")

    st.subheader("📈 株価チャート")
    hist = get_yf_history(row["yf_ticker"], period_map[period_label])
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
        st.dataframe(
            related_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]],
            use_container_width=True,
            hide_index=True,
        )

# -----------------------------
# UI
# -----------------------------
st.markdown('<div class="main-title">AI関連株コード辞典 v4</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">yfinance + FMP + Alpha Vantage で自動データを補完する試作版です。</div>', unsafe_allow_html=True)

st.sidebar.title("🔎 操作メニュー")
mode = st.sidebar.radio("表示モード", ["ティッカー検索", "キーワード検索", "カテゴリ表示", "全銘柄一覧", "API設定確認"])
period_label = st.sidebar.selectbox("チャート期間", ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"], index=2)
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

elif mode == "全銘柄一覧":
    st.subheader("登録銘柄一覧")
    st.dataframe(df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "official_ir_url"]], use_container_width=True, hide_index=True)

elif mode == "API設定確認":
    st.subheader("API設定確認")
    st.write("FMP_API_KEY:", "設定済み" if FMP_API_KEY else "未設定")
    st.write("ALPHAVANTAGE_API_KEY:", "設定済み" if ALPHAVANTAGE_API_KEY else "未設定")
    st.markdown("""
    ### Streamlit Cloudで設定する場所
    App管理画面 → Settings → Secrets

    ### 入れる内容の例
    ```toml
    FMP_API_KEY = "ここにFMPのAPIキー"
    ALPHAVANTAGE_API_KEY = "ここにAlpha VantageのAPIキー"
    ```

    片方だけでもOKです。
    """)

st.markdown("---")
with st.expander("🛠 銘柄データの追加・修正方法"):
    st.markdown("""
    `stocks.csv` に1行追加します。

    大事な列：
    - `ticker`：表示用ティッカー
    - `yf_ticker`：yfinance取得用コード。日本株は例：`7203.T`
    - `official_ir_url`：公式IRページURL。空欄でもOK
    - `related`：関連銘柄。カンマ区切り

    無料APIは制限があるので、取得できない項目は「未取得」になります。
    """)
