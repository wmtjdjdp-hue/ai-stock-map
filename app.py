
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
from urllib.parse import quote_plus
import requests
import yfinance as yf

st.set_page_config(page_title="AI関連株コード辞典 v9", page_icon="📈", layout="wide")

# ============================================================
# AI関連株コード辞典 v9
# 目的：
# yfinanceを中心に、FMP / Alpha Vantage / Finnhub の無料APIを補助として使う構造
#
# 優先順位：
# 1. yfinance
# 2. FMP_API_KEY があれば Financial Modeling Prep
# 3. FINNHUB_API_KEY があれば Finnhub
# 4. ALPHAVANTAGE_API_KEY があれば Alpha Vantage
# 5. 取れなければ「未取得」
#
# Streamlit Cloud の Secrets に入れる例：
# FMP_API_KEY = "あなたのFMPキー"
# ALPHAVANTAGE_API_KEY = "あなたのAlpha Vantageキー"
# FINNHUB_API_KEY = "あなたのFinnhubキー"
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
# お気に入り登録：セッション内保存
# 注意：Streamlit Community Cloudでは、ここでの登録はセッション内保存です。
# 永続保存したい場合は、次段階でGoogle Sheets / Supabase / SQLite等に接続します。
# -----------------------------
def init_favorites():
    if "favorite_stocks" not in st.session_state:
        st.session_state.favorite_stocks = []

init_favorites()

def add_favorite_stock(ticker, company, category):
    ticker = str(ticker).upper().strip()
    company = str(company).strip()
    category = str(category).strip() or "未分類"

    # 同じティッカーが既にあればカテゴリを更新
    updated = False
    for item in st.session_state.favorite_stocks:
        if item["ticker"].upper() == ticker:
            item["company"] = company
            item["category"] = category
            updated = True
            break

    if not updated:
        st.session_state.favorite_stocks.append({
            "ticker": ticker,
            "company": company,
            "category": category,
        })

def remove_favorite_stock(ticker):
    ticker = str(ticker).upper().strip()
    st.session_state.favorite_stocks = [
        x for x in st.session_state.favorite_stocks
        if x["ticker"].upper() != ticker
    ]

def favorite_dataframe():
    if not st.session_state.favorite_stocks:
        return pd.DataFrame(columns=["ticker", "company", "category"])
    return pd.DataFrame(st.session_state.favorite_stocks)

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
FINNHUB_API_KEY = get_secret("FINNHUB_API_KEY")

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


def currency_symbol(currency):
    c = str(currency or "").upper()
    symbols = {
        "USD": "$",
        "JPY": "¥",
        "KRW": "₩",
        "EUR": "€",
        "GBP": "£",
        "CAD": "C$",
        "AUD": "A$",
        "CHF": "CHF",
        "HKD": "HK$",
        "CNY": "¥",
    }
    return symbols.get(c, c + " " if c else "")

def fmt_price_short(x, currency=""):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{currency_symbol(currency)}{float(x):,.2f}"
    except Exception:
        return str(x)

def fmt_price(x, currency=""):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{currency_symbol(currency)}{float(x):,.2f}"
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


def metric_card(label, value, sub=None):
    sub_html = f'<div class="metric-sub">{sub}</div>' if sub else '<div class="metric-sub">&nbsp;</div>'
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label2">{label}</div>
            <div class="metric-value2">{value}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

def delta_text(change_pct):
    if change_pct is None or change_pct == "" or pd.isna(change_pct):
        return "前日比：未取得"
    try:
        sign = "+" if float(change_pct) >= 0 else ""
        return f"前日比：{sign}{float(change_pct):.2f}%"
    except Exception:
        return f"前日比：{change_pct}"

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
# Finnhub
# -----------------------------

@st.cache_data(ttl=3600)
def get_finnhub_data(symbol, api_key):
    result = {
        "source": "Finnhub",
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
        # Quote endpoint
        url = "https://finnhub.io/api/v1/quote"
        params = {"symbol": symbol, "token": api_key}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            q = r.json()
            result["price"] = pick_first(q.get("c"))
            result["prev_close"] = pick_first(q.get("pc"))
            result["change_pct"] = pick_first(q.get("dp"))

        # Basic financials endpoint
        url = "https://finnhub.io/api/v1/stock/metric"
        params = {"symbol": symbol, "metric": "all", "token": api_key}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            data = r.json()
            m = data.get("metric", {}) if isinstance(data, dict) else {}

            # FinnhubのmarketCapitalizationは多くの場合「百万ドル」単位なので、表示用にドルへ変換
            mc = pick_first(m.get("marketCapitalization"))
            if mc is not None:
                try:
                    result["market_cap"] = float(mc) * 1_000_000
                except Exception:
                    result["market_cap"] = mc

            result["per"] = pick_first(
                m.get("peBasicExclExtraTTM"),
                m.get("peNormalizedAnnual"),
                m.get("peTTM")
            )
            result["forward_pe"] = pick_first(m.get("forwardPE"))
            result["pbr"] = pick_first(
                m.get("pbAnnual"),
                m.get("pbQuarterly")
            )
            result["fifty_two_high"] = pick_first(m.get("52WeekHigh"))
            result["fifty_two_low"] = pick_first(m.get("52WeekLow"))
            result["dividend_yield"] = pick_first(
                m.get("currentDividendYieldTTM"),
                m.get("dividendYieldIndicatedAnnual")
            )

        # Company profile endpoint
        url = "https://finnhub.io/api/v1/stock/profile2"
        params = {"symbol": symbol, "token": api_key}
        r = requests.get(url, params=params, timeout=10)
        if r.ok:
            p = r.json()
            result["currency"] = pick_first(p.get("currency"), result["currency"])
            result["industry"] = pick_first(p.get("finnhubIndustry"), "")

    except Exception:
        pass

    return result

# -----------------------------
# 複数データ源を合成
# -----------------------------
@st.cache_data(ttl=1800)
def get_combined_data(yf_ticker, fmp_key, alpha_key, finnhub_key):
    yf_data = get_yfinance_data(yf_ticker)

    symbol = to_alpha_symbol(yf_ticker)
    fmp_data = get_fmp_data(symbol, fmp_key) if symbol else {}
    alpha_data = get_alpha_data(symbol, alpha_key) if symbol else {}
    finnhub_data = get_finnhub_data(symbol, finnhub_key) if symbol else {}

    result = {}
    source_map = {}

    keys = [
        "price", "prev_close", "change_pct", "market_cap",
        "per", "forward_pe", "pbr", "forward_pbr",
        "fifty_two_high", "fifty_two_low", "dividend_yield",
        "currency", "sector", "industry"
    ]

    # 優先順位は yfinance -> FMP -> Finnhub -> Alpha Vantage
    for k in keys:
        candidates = [
            ("yfinance", yf_data.get(k)),
            ("FMP", fmp_data.get(k) if fmp_data else None),
            ("Finnhub", finnhub_data.get(k) if finnhub_data else None),
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

    return result, source_map, yf_data, fmp_data, alpha_data, finnhub_data

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
    .metric-card {
        background:#fff;
        border:1px solid #e5e7eb;
        border-radius:16px;
        padding:12px 14px;
        min-height:96px;
        box-shadow:0 3px 14px rgba(0,0,0,.04);
        overflow:hidden;
        margin-bottom:10px;
    }
    .metric-label2 {
        color:#64748b;
        font-size:13px;
        font-weight:800;
        margin-bottom:6px;
        white-space:nowrap;
    }
    .metric-value2 {
        color:#111827;
        font-size:clamp(20px, 2.8vw, 32px);
        font-weight:850;
        line-height:1.05;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
    }
    .metric-sub {
        color:#64748b;
        font-size:12px;
        font-weight:700;
        margin-top:6px;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
    }
    .profile-grid {
        background:#f8fafc;
        border:1px solid #e5e7eb;
        border-radius:16px;
        padding:12px 14px;
        margin-top:10px;
        margin-bottom:10px;
    }
    .profile-title {
        font-weight:900;
        color:#111827;
        margin-bottom:6px;
    }
    .profile-row {
        color:#334155;
        font-size:14px;
        line-height:1.6;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# 関連図
# -----------------------------
def make_mindmap_html(selected_ticker=None):
    base_categories = [
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

    # お気に入り登録された銘柄を、選択カテゴリへ追加
    category_map = {cat: list(tickers) for cat, tickers in base_categories}
    favorite_lookup = {}

    for item in st.session_state.get("favorite_stocks", []):
        cat = item.get("category", "未分類") or "未分類"
        ticker = item.get("ticker", "").upper()
        company = item.get("company", "")
        if not ticker:
            continue
        if cat not in category_map:
            category_map[cat] = []
        if ticker not in category_map[cat]:
            category_map[cat].append(ticker)
        favorite_lookup[ticker] = company

    selected = selected_ticker.upper() if selected_ticker else ""
    blocks = []

    for cat, tickers in category_map.items():
        items = []
        for t in tickers:
            hit = df[(df["ticker"] == t) | (df["yf_ticker"] == t)]
            if len(hit):
                row = hit.iloc[0]
                display_ticker = row["ticker"]
                name = row["company"]
            else:
                display_ticker = t
                name = favorite_lookup.get(t, "")

            active = " active" if selected in [display_ticker.upper(), t.upper()] else ""
            items.append(f'<div class="node stock{active}">{display_ticker}<br><small>{name}</small></div>')

        blocks.append(
            f"<div class='branch'><div class='node category'>{cat}</div><div class='stocks'>{''.join(items)}</div></div>"
        )

    html = f"""
    <html><head><style>
    body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fafafa;margin:0;padding:10px;overflow-x:hidden;}}
    .map {{
        display:flex;
        flex-direction:column;
        gap:14px;
        align-items:center;
        overflow-x:hidden;
        overflow-y:visible;
        padding:12px;
        border:1px solid #e5e7eb;
        border-radius:18px;
        background:white;
        box-sizing:border-box;
        width:100%;
        max-width:100%;
    }}
    .center {{
        width:100%;
        display:flex;
        align-items:center;
        justify-content:center;
        padding:4px 0 8px 0;
        position:sticky;
        top:0;
        background:white;
        z-index:5;
        border-bottom:1px solid #f1f5f9;
    }}
    .ai {{
        width:92px;
        height:92px;
        border-radius:24px;
        background:#111827;
        color:white;
        font-size:38px;
        font-weight:900;
        display:flex;
        align-items:center;
        justify-content:center;
        box-shadow:0 8px 22px rgba(0,0,0,.18);
    }}
    .branches {{
        display:grid;
        grid-template-columns:repeat(3, 1fr);
        gap:12px;
        width:100%;
        max-width:100%;
        box-sizing:border-box;
    }}
    .branch {{
        border:1px solid #e5e7eb;
        border-radius:16px;
        padding:10px;
        background:#fff;
        min-width:0;
        box-sizing:border-box;
    }}
    .node.category {{font-weight:900;font-size:18px;border-bottom:3px solid #ff7ab6;display:inline-block;margin-bottom:8px;}}
    .stocks {{display:flex;flex-wrap:wrap;gap:8px;}}
    .node.stock {{
        border:1px solid #d1d5db;
        border-radius:12px;
        padding:8px 10px;
        min-width:0;
        width:calc(50% - 4px);
        box-sizing:border-box;
        background:#f9fafb;
        font-weight:900;
        line-height:1.15;
        overflow:hidden;
        text-overflow:ellipsis;
    }}
    .node.stock small {{
        display:block;
        font-weight:500;
        color:#555;
        font-size:11px;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
    }}
    .node.stock.active {{background:#fff7d6;border:3px solid #f59e0b;transform:scale(1.01);}}
    @media (max-width: 760px) {{
        .branches {{grid-template-columns:1fr;}}
        .node.stock {{width:100%;}}
        .ai {{width:82px;height:82px;font-size:34px;}}
    }}
    </style></head><body>
    <div class="map"><div class="center"><div class="ai">AI</div></div><div class="branches">{''.join(blocks)}</div></div>
    </body></html>
    """
    return html


def make_virtual_row(ticker):
    """
    stocks.csvに未登録の銘柄でも表示できるようにする仮データ。
    会社名や分類はAPI取得後に一部補完される。
    """
    t = str(ticker).strip().upper()
    company = t
    category = "未分類"
    business = "この銘柄はまだstocks.csvに登録されていません。株価データと外部リンクのみ表示します。"
    ai_relation = "AI関連度・カテゴリ・関連銘柄は未登録です。必要ならstocks.csvに追加してください。"
    ai_score = 0
    keywords = "未登録"
    related = ""
    official_ir_url = ""

    try:
        yf_data = get_yfinance_data(t)
        if yf_data.get("sector") or yf_data.get("industry"):
            category = yf_data.get("sector") or "未分類"
            business = f'Yahoo Finance分類：{yf_data.get("sector", "")} / {yf_data.get("industry", "")}'
        # yfinanceのinfoは重いので、ここでは最小限
        try:
            info = yf.Ticker(t).info or {}
            company = info.get("longName") or info.get("shortName") or t
            if info.get("sector") or info.get("industry"):
                category = info.get("sector") or category
                business = f'Yahoo Finance分類：{info.get("sector", "")} / {info.get("industry", "")}'
        except Exception:
            pass
    except Exception:
        pass

    return pd.Series({
        "ticker": t,
        "yf_ticker": t,
        "company": company,
        "category": category,
        "business": business,
        "ai_relation": ai_relation,
        "ai_score": ai_score,
        "keywords": keywords,
        "related": related,
        "official_ir_url": official_ir_url,
        "_virtual": True,
    })

def show_add_to_db_hint(row):
    if bool(row.get("_virtual", False)):
        st.markdown(
            """
            <div class="notice">
            <b>この銘柄はまだAI関連株DBには未登録です。</b><br>
            株価・チャート・外部リンクは表示できます。<br>
            AIカテゴリ、関連図、関連銘柄に入れたい場合は、下の「stocks.csvに追加する行」をコピーして追加してください。
            </div>
            """,
            unsafe_allow_html=True,
        )
        sample = f'{row["ticker"]},{row["yf_ticker"]},{row["company"]},未分類,事業内容を入力,AIとの関係を入力,3,キーワードを入力,"",'
        st.code(sample, language="csv")

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


def show_favorite_register(row, display_category):
    st.subheader("⭐ AI関連図にお気に入り登録")

    default_categories = sorted(set(
        df["category"].dropna().astype(str).tolist()
        + [x.get("category", "") for x in st.session_state.get("favorite_stocks", [])]
        + ["GPU", "メモリー", "冷却", "電力", "原子力", "光通信", "データセンター", "半導体製造装置", "素材", "日本AI関連", "未分類"]
    ))

    default_index = 0
    if display_category in default_categories:
        default_index = default_categories.index(display_category)

    c1, c2 = st.columns([2, 1])
    with c1:
        selected_category = st.selectbox(
            "登録するカテゴリ",
            default_categories,
            index=default_index,
            key=f"fav_cat_{row['ticker']}",
        )
    with c2:
        custom_category = st.text_input(
            "新カテゴリを作る場合",
            value="",
            key=f"fav_custom_{row['ticker']}",
            placeholder="例：AI通信・クラウド",
        )

    final_category = custom_category.strip() if custom_category.strip() else selected_category

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("この銘柄をAI関連図に登録", key=f"fav_add_{row['ticker']}", use_container_width=True):
            add_favorite_stock(row["ticker"], row["company"], final_category)
            st.success(f'{row["ticker"]} を「{final_category}」に登録しました。左メニューの「AI関連図」で確認できます。')
    with b2:
        if st.button("この銘柄を登録解除", key=f"fav_remove_{row['ticker']}", use_container_width=True):
            remove_favorite_stock(row["ticker"])
            st.info(f'{row["ticker"]} をお気に入りから解除しました。')

    st.caption("※ 現在のお気に入り登録はセッション内保存です。サイトを再起動すると消える場合があります。永続保存は次段階で追加できます。")

def show_stock_page(row):
    combined, source_map, yf_data, fmp_data, alpha_data, finnhub_data = get_combined_data(row["yf_ticker"], FMP_API_KEY, ALPHAVANTAGE_API_KEY, FINNHUB_API_KEY)

    # 未登録銘柄でも、取得できた分類を優先して表示
    display_category = row.get("category", "未分類")
    if bool(row.get("_virtual", False)) and combined.get("sector"):
        display_category = combined.get("sector")
    display_industry = combined.get("industry", "")
    display_business = row.get("business", "")
    if bool(row.get("_virtual", False)) and (combined.get("sector") or combined.get("industry")):
        display_business = f"取得分類：{combined.get('sector','')} / {combined.get('industry','')}"

    st.markdown('<div class="hero-card">', unsafe_allow_html=True)
    col1, col2 = st.columns([1.1, 2])
    with col1:
        st.markdown(f'<div class="hero-ticker">{row["ticker"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-company">{row["company"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">{display_category}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">AI関連度 {stars(row["ai_score"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="badge">取得コード {row["yf_ticker"]}</span>', unsafe_allow_html=True)
    with col2:
        st.write("**何を作るか / 事業内容**")
        st.write(display_business)
        st.write("**AIとのつながり**")
        st.write(row["ai_relation"])
        st.markdown(
            f"""
            <div class="profile-grid">
                <div class="profile-title">分類</div>
                <div class="profile-row"><b>セクター：</b>{display_category or "未取得"}</div>
                <div class="profile-row"><b>業種：</b>{display_industry or "未取得"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    show_add_to_db_hint(row)

    show_external_links(row)

    show_favorite_register(row, display_category)

    st.subheader("📊 自動取得データ：複数ソース補完")
    if not FMP_API_KEY and not ALPHAVANTAGE_API_KEY and not FINNHUB_API_KEY:
        st.markdown(
            """
            <div class="notice">
            現在は <b>yfinanceのみ</b> で取得しています。<br>
            FMP_API_KEY / ALPHAVANTAGE_API_KEY / FINNHUB_API_KEY を Streamlit Secrets に入れると、PER/PBR/時価総額の補完ができます。
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
        if FINNHUB_API_KEY:
            active.append("Finnhub")
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
    with c1:
        metric_card("株価", fmt_price(combined["price"], combined["currency"]), delta_text(combined["change_pct"]))
    with c2:
        metric_card("時価総額", fmt_market_cap(combined["market_cap"]), f'取得元：{source_map.get("market_cap", "未取得")}')
    with c3:
        metric_card("PER", fmt_num(combined["per"]), f'取得元：{source_map.get("per", "未取得")}')
    with c4:
        metric_card("予想PER", fmt_num(combined["forward_pe"]), f'取得元：{source_map.get("forward_pe", "未取得")}')
    with c5:
        metric_card("PBR", fmt_num(combined["pbr"]), f'取得元：{source_map.get("pbr", "未取得")}')

    dy = None
    if combined["dividend_yield"] is not None:
        try:
            dy = float(combined["dividend_yield"]) * 100 if float(combined["dividend_yield"]) < 1 else float(combined["dividend_yield"])
        except Exception:
            dy = combined["dividend_yield"]

    c6, c7, c8, c9 = st.columns(4)
    with c6:
        metric_card("前日終値", fmt_price(combined["prev_close"], combined["currency"]), f'取得元：{source_map.get("prev_close", "未取得")}')
    with c7:
        metric_card("52週高値", fmt_price(combined["fifty_two_high"], combined["currency"]), f'取得元：{source_map.get("fifty_two_high", "未取得")}')
    with c8:
        metric_card("52週安値", fmt_price(combined["fifty_two_low"], combined["currency"]), f'取得元：{source_map.get("fifty_two_low", "未取得")}')
    with c9:
        metric_card("配当利回り", fmt_percent(dy), f'取得元：{source_map.get("dividend_yield", "未取得")}')

    c10, c11 = st.columns(2)
    with c10:
        metric_card("予想PBR", fmt_num(combined["forward_pbr"]), "無料APIでは未取得になりやすい")
    with c11:
        metric_card("データ取得コード", row["yf_ticker"], "yfinance / API用コード")

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
st.markdown('<div class="main-title">AI関連株コード辞典 v9</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">AI関連図を縦スクロール専用レイアウトに改善。AIロゴを上部中央に配置した版です。</div>', unsafe_allow_html=True)

st.sidebar.title("🔎 操作メニュー")
mode = st.sidebar.radio("表示モード", ["ティッカー検索", "キーワード検索", "カテゴリ表示", "AI関連図", "全銘柄一覧", "API設定確認"])
period_label = st.sidebar.selectbox("チャート期間", ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"], index=2)
st.sidebar.markdown("---")
st.sidebar.caption("日本株例：7203.T / 9984.T / 6857.T")
st.sidebar.caption("米国株例：NVDA / AAPL / MSFT / T")
st.sidebar.caption("AI関連図は左メニューから確認できます。")

if mode == "ティッカー検索":
    ticker = st.text_input("ティッカーコードを入力", value="NVDA").strip().upper()
    hit = df[(df["ticker"] == ticker) | (df["yf_ticker"] == ticker)]

    if hit.empty:
        virtual_row = make_virtual_row(ticker)
        show_stock_page(virtual_row)
    else:
        row = hit.iloc[0].copy()
        row["_virtual"] = False
        show_stock_page(row)

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

elif mode == "AI関連図":
    st.subheader("🗺 AI関連図")
    st.markdown(
        """
        <div class="notice">
        検索した銘柄を「AI関連図にお気に入り登録」すると、ここで選んだカテゴリの中に追加表示されます。<br>
        現在はセッション内保存です。永続保存したい場合は、次にGoogle SheetsやSupabase連携を追加します。
        </div>
        """,
        unsafe_allow_html=True,
    )
    components.html(make_mindmap_html(), height=980, scrolling=False)

    st.subheader("⭐ お気に入り登録済み銘柄")
    fav_df = favorite_dataframe()
    if fav_df.empty:
        st.info("まだお気に入り登録された銘柄はありません。ティッカー検索から登録してください。")
    else:
        st.dataframe(fav_df, use_container_width=True, hide_index=True)
        remove_target = st.selectbox("解除する銘柄を選択", fav_df["ticker"].tolist())
        if st.button("選択した銘柄を解除", use_container_width=True):
            remove_favorite_stock(remove_target)
            st.success(f"{remove_target} を解除しました。画面を再読み込みすると反映されます。")

elif mode == "全銘柄一覧":
    st.subheader("登録銘柄一覧")
    st.dataframe(df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "official_ir_url"]], use_container_width=True, hide_index=True)

elif mode == "API設定確認":
    st.subheader("API設定確認")
    st.write("FMP_API_KEY:", "設定済み" if FMP_API_KEY else "未設定")
    st.write("ALPHAVANTAGE_API_KEY:", "設定済み" if ALPHAVANTAGE_API_KEY else "未設定")
    st.write("FINNHUB_API_KEY:", "設定済み" if FINNHUB_API_KEY else "未設定")
    st.markdown("""
    ### Streamlit Cloudで設定する場所
    App管理画面 → Settings → Secrets

    ### 入れる内容の例
    ```toml
    FMP_API_KEY = "ここにFMPのAPIキー"
    ALPHAVANTAGE_API_KEY = "ここにAlpha VantageのAPIキー"
    FINNHUB_API_KEY = "ここにFinnhubのAPIキー"
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

    未登録ティッカーも検索できますが、AI分類・関連銘柄・関連図に入れるには stocks.csv に追加してください。無料APIは制限があるので、取得できない項目は「未取得」になります。
    """)
