
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
from urllib.parse import quote_plus
import requests
import yfinance as yf

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

st.set_page_config(page_title="AI関連株コード辞典 v23", page_icon="📈", layout="wide")

# ============================================================
# AI関連株コード辞典 v23 Clean
# 目的：
# - 登録済み銘柄は stocks.csv を優先
# - 未登録銘柄でも、無料API/yfinanceから会社名・業種・分類・事業内容を自動取得
# - AIとのつながりは、取得した業種/説明文から仮メモ生成
# - スクレイピングではなく、API/公開エンドポイントのみ使用
# ============================================================

@st.cache_data
def load_data():
    path = Path(__file__).parent / "stocks.csv"
    df = pd.read_csv(path)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["yf_ticker"] = df["yf_ticker"].astype(str).str.upper()
    for col in ["company", "category", "business", "ai_relation", "keywords", "related", "official_ir_url"]:
        df[col] = df[col].fillna("")
    return df

df = load_data()

def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""

FMP_API_KEY = get_secret("FMP_API_KEY")
ALPHAVANTAGE_API_KEY = get_secret("ALPHAVANTAGE_API_KEY")
FINNHUB_API_KEY = get_secret("FINNHUB_API_KEY")

if "favorite_stocks" not in st.session_state:
    st.session_state.favorite_stocks = []
if "last_ticker" not in st.session_state:
    st.session_state.last_ticker = "NVDA"
if "ticker_search_input" not in st.session_state:
    st.session_state.ticker_search_input = st.session_state.last_ticker

def sync_ticker_input():
    value = st.session_state.get("ticker_search_input", "").strip().upper()
    if value:
        st.session_state.last_ticker = value

# -----------------------------
# 表示ユーティリティ
# -----------------------------
def pick_first(*values):
    for v in values:
        if v is not None and v != "" and not (isinstance(v, float) and pd.isna(v)):
            return v
    return None

def stars(n):
    try:
        n = int(n)
    except Exception:
        n = 0
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)

def currency_symbol(currency):
    c = str(currency or "").upper()
    return {
        "USD": "$",
        "JPY": "¥",
        "KRW": "₩",
        "EUR": "€",
        "GBP": "£",
        "CAD": "C$",
        "AUD": "A$",
        "HKD": "HK$",
        "CNY": "¥",
    }.get(c, c + " " if c else "")

def fmt_price(x, currency=""):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{currency_symbol(currency)}{float(x):,.2f}"
    except Exception:
        return str(x)

def fmt_num(x, decimals=2):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)

def fmt_percent(x):
    if x is None or x == "" or pd.isna(x):
        return "未取得"
    try:
        sign = "+" if float(x) >= 0 else ""
        return f"{sign}{float(x):.2f}%"
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
    return f"前日比：{fmt_percent(change_pct)}"

def to_api_symbol(yf_ticker):
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
def get_yf_data(yf_ticker):
    result = {
        "price": None, "prev_close": None, "change_pct": None,
        "market_cap": None, "per": None, "forward_pe": None, "pbr": None,
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None,
        "currency": "", "company": "", "sector": "", "industry": "", "description": "",
    }
    try:
        t = yf.Ticker(yf_ticker)

        try:
            fast = t.fast_info
            def fget(obj, key):
                try:
                    return getattr(obj, key)
                except Exception:
                    try:
                        return obj.get(key)
                    except Exception:
                        return None
            result["price"] = pick_first(fget(fast, "last_price"), fget(fast, "lastPrice"))
            result["prev_close"] = pick_first(fget(fast, "previous_close"), fget(fast, "previousClose"))
            result["market_cap"] = pick_first(fget(fast, "market_cap"), fget(fast, "marketCap"))
            result["currency"] = pick_first(fget(fast, "currency"), "")
            result["fifty_two_high"] = pick_first(fget(fast, "year_high"), fget(fast, "yearHigh"))
            result["fifty_two_low"] = pick_first(fget(fast, "year_low"), fget(fast, "yearLow"))
        except Exception:
            pass

        try:
            info = t.info or {}
            result["company"] = pick_first(info.get("longName"), info.get("shortName"), "")
            result["sector"] = pick_first(info.get("sector"), "")
            result["industry"] = pick_first(info.get("industry"), "")
            result["description"] = pick_first(info.get("longBusinessSummary"), "")
            result["price"] = pick_first(result["price"], info.get("currentPrice"), info.get("regularMarketPrice"))
            result["prev_close"] = pick_first(result["prev_close"], info.get("previousClose"))
            result["market_cap"] = pick_first(result["market_cap"], info.get("marketCap"))
            result["per"] = pick_first(info.get("trailingPE"))
            result["forward_pe"] = pick_first(info.get("forwardPE"))
            result["pbr"] = pick_first(info.get("priceToBook"))
            result["fifty_two_high"] = pick_first(result["fifty_two_high"], info.get("fiftyTwoWeekHigh"))
            result["fifty_two_low"] = pick_first(result["fifty_two_low"], info.get("fiftyTwoWeekLow"))
            result["dividend_yield"] = pick_first(info.get("dividendYield"))
            result["currency"] = pick_first(result["currency"], info.get("currency"), "")
        except Exception:
            pass

        try:
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                closes = hist["Close"].dropna().tolist()
                if len(closes) >= 1:
                    result["price"] = pick_first(result["price"], closes[-1])
                if len(closes) >= 2:
                    result["prev_close"] = pick_first(result["prev_close"], closes[-2])
        except Exception:
            pass

        if result["price"] is not None and result["prev_close"] not in [None, 0]:
            result["change_pct"] = (float(result["price"]) - float(result["prev_close"])) / float(result["prev_close"]) * 100
    except Exception:
        pass
    return result

@st.cache_data(ttl=1800)
def get_yf_history(yf_ticker, period):
    try:
        hist = yf.Ticker(yf_ticker).history(period=period)
        if hist is None or hist.empty:
            return pd.DataFrame()
        return hist.reset_index()
    except Exception:
        return pd.DataFrame()


# -----------------------------
# Yahoo Finance Search fallback
# APIキーなしで会社名を補完するための検索エンドポイント。
# 特に T / D / ARM など、yfinance infoが返らない時の会社名補完に使う。
# -----------------------------
COMMON_TICKER_FALLBACK = {
    "T": {
        "company": "AT&T Inc.",
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "description": "AT&T Inc. is a telecommunications company providing wireless, broadband, and communications services.",
    },
    "D": {
        "company": "Dominion Energy, Inc.",
        "sector": "Utilities",
        "industry": "Utilities - Regulated Electric",
        "description": "Dominion Energy, Inc. is an energy and utility company involved in electricity and natural gas infrastructure.",
    },
    "ARM": {
        "company": "Arm Holdings plc",
        "sector": "Technology",
        "industry": "Semiconductors",
        "description": "Arm Holdings plc licenses CPU architecture and semiconductor IP used in mobile, edge, cloud, and AI-related chips.",
    },
    "AAPL": {
        "company": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "description": "Apple Inc. designs devices, software, services, and silicon platforms with growing AI features across its ecosystem.",
    },
    "MSFT": {
        "company": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "description": "Microsoft Corporation provides cloud, software, productivity platforms, and AI services through Azure and Copilot.",
    },
    "GOOGL": {
        "company": "Alphabet Inc.",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "description": "Alphabet Inc. operates Google, cloud services, advertising platforms, and AI research/products.",
    },
}

@st.cache_data(ttl=3600)
def get_yahoo_search_data(symbol):
    result = {
        "company": "",
        "sector": "",
        "industry": "",
        "description": "",
        "currency": "",
    }
    s = str(symbol).upper().strip()

    # 先に代表銘柄の安全な補完
    if s in COMMON_TICKER_FALLBACK:
        result.update(COMMON_TICKER_FALLBACK[s])

    # Yahoo Financeの検索エンドポイントから会社名を補完
    try:
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {"q": s, "quotesCount": 8, "newsCount": 0, "enableFuzzyQuery": False}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=8)
        if r.ok:
            data = r.json()
            quotes = data.get("quotes", [])
            best = None

            # 完全一致を優先
            for q in quotes:
                if str(q.get("symbol", "")).upper() == s:
                    best = q
                    break

            # 完全一致が無ければ最初の株式候補
            if best is None:
                for q in quotes:
                    if q.get("quoteType") in ["EQUITY", "ETF"]:
                        best = q
                        break

            if best:
                result["company"] = pick_first(
                    best.get("longname"),
                    best.get("shortname"),
                    result.get("company"),
                    ""
                )
                result["sector"] = pick_first(best.get("sector"), result.get("sector"), "")
                result["industry"] = pick_first(best.get("industry"), result.get("industry"), "")
                result["currency"] = pick_first(best.get("currency"), result.get("currency"), "")
    except Exception:
        pass

    return result

# -----------------------------
# FMP
# -----------------------------
@st.cache_data(ttl=3600)
def get_fmp_data(symbol, api_key):
    result = {
        "price": None, "prev_close": None, "change_pct": None,
        "market_cap": None, "per": None, "forward_pe": None, "pbr": None,
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None,
        "currency": "", "company": "", "sector": "", "industry": "", "description": "",
    }
    if not symbol or not api_key:
        return result
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={api_key}", timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                p = data[0]
                result["company"] = pick_first(p.get("companyName"), "")
                result["sector"] = pick_first(p.get("sector"), "")
                result["industry"] = pick_first(p.get("industry"), "")
                result["description"] = pick_first(p.get("description"), "")
                result["price"] = pick_first(p.get("price"))
                result["market_cap"] = pick_first(p.get("mktCap"))
                result["currency"] = pick_first(p.get("currency"), "USD")

        r = requests.get(f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={api_key}", timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                q = data[0]
                result["price"] = pick_first(result["price"], q.get("price"))
                result["prev_close"] = pick_first(q.get("previousClose"))
                result["change_pct"] = pick_first(q.get("changesPercentage"))
                result["market_cap"] = pick_first(result["market_cap"], q.get("marketCap"))
                result["per"] = pick_first(q.get("pe"))
                result["fifty_two_high"] = pick_first(q.get("yearHigh"))
                result["fifty_two_low"] = pick_first(q.get("yearLow"))

        r = requests.get(f"https://financialmodelingprep.com/api/v3/ratios-ttm/{symbol}?apikey={api_key}", timeout=10)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                rr = data[0]
                result["per"] = pick_first(result["per"], rr.get("peRatioTTM"))
                result["pbr"] = pick_first(rr.get("priceToBookRatioTTM"))
                result["dividend_yield"] = pick_first(rr.get("dividendYieldTTM"), rr.get("dividendYielTTM"))
    except Exception:
        pass
    return result

# -----------------------------
# Alpha Vantage
# -----------------------------
@st.cache_data(ttl=3600)
def get_alpha_data(symbol, api_key):
    result = {
        "price": None, "prev_close": None, "change_pct": None,
        "market_cap": None, "per": None, "forward_pe": None, "pbr": None,
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None,
        "currency": "USD", "company": "", "sector": "", "industry": "", "description": "",
    }
    if not symbol or not api_key:
        return result
    try:
        url = "https://www.alphavantage.co/query"
        r = requests.get(url, params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key}, timeout=10)
        if r.ok:
            q = r.json().get("Global Quote", {})
            result["price"] = pick_first(q.get("05. price"))
            result["prev_close"] = pick_first(q.get("08. previous close"))
            result["change_pct"] = pick_first(str(q.get("10. change percent", "")).replace("%", ""))

        r = requests.get(url, params={"function": "OVERVIEW", "symbol": symbol, "apikey": api_key}, timeout=10)
        if r.ok:
            o = r.json()
            result["company"] = pick_first(o.get("Name"), "")
            result["sector"] = pick_first(o.get("Sector"), "")
            result["industry"] = pick_first(o.get("Industry"), "")
            result["description"] = pick_first(o.get("Description"), "")
            result["market_cap"] = pick_first(o.get("MarketCapitalization"))
            result["per"] = pick_first(o.get("PERatio"))
            result["forward_pe"] = pick_first(o.get("ForwardPE"))
            result["pbr"] = pick_first(o.get("PriceToBookRatio"))
            result["fifty_two_high"] = pick_first(o.get("52WeekHigh"))
            result["fifty_two_low"] = pick_first(o.get("52WeekLow"))
            result["dividend_yield"] = pick_first(o.get("DividendYield"))
    except Exception:
        pass
    return result

# -----------------------------
# Finnhub
# -----------------------------
@st.cache_data(ttl=3600)
def get_finnhub_data(symbol, api_key):
    result = {
        "price": None, "prev_close": None, "change_pct": None,
        "market_cap": None, "per": None, "forward_pe": None, "pbr": None,
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None,
        "currency": "USD", "company": "", "sector": "", "industry": "", "description": "",
    }
    if not symbol or not api_key:
        return result
    try:
        r = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": symbol, "token": api_key}, timeout=10)
        if r.ok:
            q = r.json()
            result["price"] = pick_first(q.get("c"))
            result["prev_close"] = pick_first(q.get("pc"))
            result["change_pct"] = pick_first(q.get("dp"))

        r = requests.get("https://finnhub.io/api/v1/stock/profile2", params={"symbol": symbol, "token": api_key}, timeout=10)
        if r.ok:
            p = r.json()
            result["company"] = pick_first(p.get("name"), "")
            result["currency"] = pick_first(p.get("currency"), result["currency"])
            result["industry"] = pick_first(p.get("finnhubIndustry"), "")

        r = requests.get("https://finnhub.io/api/v1/stock/metric", params={"symbol": symbol, "metric": "all", "token": api_key}, timeout=10)
        if r.ok:
            m = r.json().get("metric", {})
            mc = pick_first(m.get("marketCapitalization"))
            if mc is not None:
                try:
                    result["market_cap"] = float(mc) * 1_000_000
                except Exception:
                    result["market_cap"] = mc
            result["per"] = pick_first(m.get("peBasicExclExtraTTM"), m.get("peNormalizedAnnual"), m.get("peTTM"))
            result["forward_pe"] = pick_first(m.get("forwardPE"))
            result["pbr"] = pick_first(m.get("pbAnnual"), m.get("pbQuarterly"))
            result["fifty_two_high"] = pick_first(m.get("52WeekHigh"))
            result["fifty_two_low"] = pick_first(m.get("52WeekLow"))
            result["dividend_yield"] = pick_first(m.get("currentDividendYieldTTM"), m.get("dividendYieldIndicatedAnnual"))
    except Exception:
        pass
    return result

# -----------------------------
# データ合成
# -----------------------------
@st.cache_data(ttl=1800)
def get_combined_data(yf_ticker, fmp_key, alpha_key, finnhub_key):
    yf_data = get_yf_data(yf_ticker)
    symbol = to_api_symbol(yf_ticker)
    yahoo_search = get_yahoo_search_data(symbol) if symbol else {}
    fmp = get_fmp_data(symbol, fmp_key) if symbol else {}
    alpha = get_alpha_data(symbol, alpha_key) if symbol else {}
    finnhub = get_finnhub_data(symbol, finnhub_key) if symbol else {}

    keys = [
        "price", "prev_close", "change_pct", "market_cap", "per", "forward_pe", "pbr",
        "fifty_two_high", "fifty_two_low", "dividend_yield", "currency",
        "company", "sector", "industry", "description"
    ]
    result, source_map = {}, {}
    for k in keys:
        # 会社概要はAPI説明文が有効なことが多いので FMP/Alpha をyfinanceより優先
        if k in ["company", "sector", "industry", "description"]:
            candidates = [
                ("FMP", fmp.get(k) if fmp else None),
                ("Alpha Vantage", alpha.get(k) if alpha else None),
                ("Finnhub", finnhub.get(k) if finnhub else None),
                ("Yahoo Search", yahoo_search.get(k) if yahoo_search else None),
                ("yfinance", yf_data.get(k)),
            ]
        else:
            candidates = [
                ("yfinance", yf_data.get(k)),
                ("FMP", fmp.get(k) if fmp else None),
                ("Finnhub", finnhub.get(k) if finnhub else None),
                ("Alpha Vantage", alpha.get(k) if alpha else None),
            ]
        value, src = None, "未取得"
        for name, v in candidates:
            if v is not None and v != "" and not (isinstance(v, float) and pd.isna(v)):
                value, src = v, name
                break
        result[k] = value
        source_map[k] = src
    return result, source_map

# -----------------------------
# 自動AI関連メモ
# -----------------------------
def auto_ai_relation(category, industry, description):
    text = f"{category} {industry} {description}".lower()

    if any(k in text for k in ["semiconductor", "gpu", "chip", "memory", "electronic", "equipment"]):
        return "半導体・GPU・メモリー・製造装置など、AI計算インフラの上流/周辺として関連候補。"
    if any(k in text for k in ["telecom", "communication", "network", "wireless", "fiber"]):
        return "通信ネットワーク・クラウド接続・データセンター間通信の観点でAI関連候補。"
    if any(k in text for k in ["utility", "electric", "power", "energy", "nuclear", "gas"]):
        return "AIデータセンターの電力需要、発電、送電、電力インフラの観点で関連候補。"
    if any(k in text for k in ["data center", "reit", "real estate", "infrastructure"]):
        return "AIサーバーを収容するデータセンター/インフラ需要の観点で関連候補。"
    if any(k in text for k in ["software", "cloud", "internet", "ai", "artificial intelligence"]):
        return "AIサービス、クラウド、ソフトウェア利用拡大の観点で関連候補。"
    if any(k in text for k in ["machinery", "industrial", "construction", "engineering", "automation"]):
        return "AIデータセンター建設、設備投資、産業自動化の観点で関連候補。"
    if any(k in text for k in ["mining", "copper", "materials", "chemical", "lithium"]):
        return "銅・素材・電池材料など、AIインフラや電力設備に必要な材料の観点で関連候補。"

    return "取得した会社概要・分類からAI関連候補として仮メモを生成。詳しい関連理由は自分メモで追記。"

def trim_text(text, max_len=420):
    text = str(text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def has_japanese(text):
    text = str(text or "")
    return any(
        ("\u3040" <= ch <= "\u30ff") or ("\u4e00" <= ch <= "\u9fff")
        for ch in text
    )

def looks_english(text):
    text = str(text or "").strip()
    if not text:
        return False
    ascii_count = sum(1 for ch in text if ord(ch) < 128 and ch.isalpha())
    return ascii_count >= max(10, len(text) * 0.25) and not has_japanese(text)

@st.cache_data(ttl=86400)
def translate_to_japanese(text):
    """
    英語で取得された会社概要を日本語へ変換。
    deep-translator が使えない場合は原文を返す。
    """
    text = str(text or "").strip()
    if not text:
        return ""
    if has_japanese(text):
        return text
    if not looks_english(text):
        return text
    if GoogleTranslator is None:
        return text

    try:
        # 長文すぎると失敗しやすいので短めに制限
        limited = text[:2500]
        return GoogleTranslator(source="auto", target="ja").translate(limited)
    except Exception:
        return text

def clean_company_name(name):
    """
    表示用に会社名を短くする。
    例：AT&T Inc. -> AT&T
    """
    name = str(name or "").strip()
    suffixes = [
        ", Inc.", " Inc.", " Inc", ", Inc",
        " Corporation", " Corp.", " Corp",
        " Incorporated",
        " plc", " PLC",
        " Ltd.", " Ltd", " Limited",
        " Co., Ltd.", " Co. Ltd.", " Company",
    ]
    for s in suffixes:
        if name.endswith(s):
            name = name[: -len(s)].strip()
    return name or str(name or "").strip()


def build_row_from_ticker(ticker):
    t = str(ticker).strip().upper()
    hit = df[(df["ticker"].str.upper() == t) | (df["yf_ticker"].str.upper() == t)]
    if not hit.empty:
        row = hit.iloc[0].copy()
        row["_virtual"] = False
        return row

    combined, source_map = get_combined_data(t, FMP_API_KEY, ALPHAVANTAGE_API_KEY, FINNHUB_API_KEY)
    company = pick_first(combined.get("company"), t)
    category = pick_first(combined.get("sector"), "未分類")
    industry = pick_first(combined.get("industry"), "")
    description = trim_text(combined.get("description"), 520)

    if description:
        business = translate_to_japanese(description)
    elif category or industry:
        business = f"取得分類：{category or '未取得'} / {industry or '未取得'}"
    else:
        business = "会社概要は未取得です。APIキーを追加すると反映される可能性があります。"

    relation = auto_ai_relation(category, industry, description)
    keywords = f"{category} {industry} {company}"

    return pd.Series({
        "ticker": t,
        "yf_ticker": t,
        "company": company,
        "category": category,
        "business": business,
        "ai_relation": relation,
        "ai_score": 3,
        "keywords": keywords,
        "related": "",
        "official_ir_url": "",
        "_virtual": True,
    })

def add_favorite_stock(ticker, company, category):
    ticker = str(ticker).upper().strip()
    category = str(category or "未分類").strip()
    updated = False
    for item in st.session_state.favorite_stocks:
        if item["ticker"].upper() == ticker:
            item["company"] = company
            item["category"] = category
            updated = True
            break
    if not updated:
        st.session_state.favorite_stocks.append({"ticker": ticker, "company": company, "category": category})

def remove_favorite_stock(ticker):
    ticker = str(ticker).upper().strip()
    st.session_state.favorite_stocks = [x for x in st.session_state.favorite_stocks if x["ticker"].upper() != ticker]

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
        links += [
            ("株探", f"https://kabutan.jp/stock/?code={code}"),
            ("株探チャート", f"https://kabutan.jp/stock/chart?code={code}"),
            ("四季報オンライン", f"https://shikiho.toyokeizai.net/stocks/{code}"),
            ("バフェットコード", f"https://www.buffett-code.com/company/{code}/"),
            ("IR BANK", f"https://irbank.net/{code}"),
        ]
    else:
        links += [
            ("株探で検索", f"https://www.google.com/search?q={quote_plus(ticker + ' 株探')}"),
            ("四季報で検索", f"https://www.google.com/search?q={quote_plus(ticker + ' 四季報')}"),
            ("バフェットコードで検索", f"https://www.google.com/search?q={quote_plus(ticker + ' バフェットコード')}"),
        ]

    if str(row.get("official_ir_url", "")).strip():
        links.append(("公式IR", str(row.get("official_ir_url")).strip()))
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
    .metric-card {background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:12px 14px;min-height:96px;box-shadow:0 3px 14px rgba(0,0,0,.04);overflow:hidden;margin-bottom:10px;}
    .metric-label2 {color:#64748b;font-size:13px;font-weight:800;margin-bottom:6px;white-space:nowrap;}
    .metric-value2 {color:#111827;font-size:clamp(20px,2.8vw,32px);font-weight:850;line-height:1.05;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .metric-sub {color:#64748b;font-size:12px;font-weight:700;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .profile-grid {background:#f8fafc;border:1px solid #e5e7eb;border-radius:16px;padding:12px 14px;margin-top:10px;margin-bottom:10px;color:#111827;}
    .profile-title {font-weight:900;color:#111827;margin-bottom:6px;}
    .profile-row {color:#334155;font-size:14px;line-height:1.6;}

    .small-label {color:#cbd5e1;font-size:13px;font-weight:800;margin-top:6px;margin-bottom:2px;}
    .hero-company-main {font-size:34px;font-weight:900;line-height:1.05;color:white;margin-bottom:14px;word-break:break-word;}
    .hero-ticker-code {font-size:42px;font-weight:900;line-height:1.0;color:white;margin-bottom:12px;}

    .identity-box {
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.22);
        border-radius: 18px;
        padding: 16px 18px;
        margin-bottom: 14px;
    }
    .identity-label {
        color: #ffffff !important;
        font-size: 15px;
        font-weight: 900;
        letter-spacing: .03em;
        opacity: 0.96;
        margin-bottom: 6px;
    }
    .identity-company {
        color: #ffffff !important;
        font-size: 38px;
        font-weight: 950;
        line-height: 1.08;
        margin-bottom: 18px;
        text-shadow: 0 2px 10px rgba(0,0,0,.28);
        word-break: break-word;
    }
    .identity-ticker {
        color: #ffffff !important;
        font-size: 46px;
        font-weight: 950;
        line-height: 1.0;
        margin-bottom: 6px;
        text-shadow: 0 2px 10px rgba(0,0,0,.28);
    }
    /* AI_STOCK_V19_IDENTITY_TABLE_CSS */

    .identity-box {
        background: #ffffff !important;
        border: 2px solid #d1d5db !important;
        border-radius: 18px !important;
        padding: 18px 20px !important;
        margin-bottom: 16px !important;
        box-shadow: 0 6px 20px rgba(0,0,0,.12) !important;
    }
    .identity-row {
        display: grid;
        grid-template-columns: 170px 1fr;
        gap: 14px;
        align-items: baseline;
        padding: 9px 0;
        border-bottom: 1px solid #eef2f7;
    }
    .identity-row:last-child {
        border-bottom: none;
    }
    .identity-label {
        color: #0f172a !important;
        font-size: 18px !important;
        font-weight: 950 !important;
        letter-spacing: .02em;
        white-space: nowrap;
        opacity: 1 !important;
    }
    .identity-company {
        color: #111827 !important;
        font-size: 34px !important;
        font-weight: 950 !important;
        line-height: 1.08 !important;
        word-break: break-word;
        text-shadow: none !important;
        margin-bottom: 0 !important;
    }
    .identity-ticker {
        color: #0b1f4d !important;
        font-size: 42px !important;
        font-weight: 950 !important;
        line-height: 1.0 !important;
        letter-spacing: .02em;
        text-shadow: none !important;
        margin-bottom: 0 !important;
    }
    @media (max-width: 720px) {
        .identity-row {
            grid-template-columns: 1fr;
            gap: 4px;
        }
        .identity-company {
            font-size: 28px !important;
        }
        .identity-ticker {
            font-size: 36px !important;
        }
    }

    /* AI_STOCK_V20_IDENTITY_BALANCE_CSS */
    .identity-box {
        background: #ffffff !important;
        border: 1.5px solid #d8dee8 !important;
        border-radius: 16px !important;
        padding: 14px 16px !important;
        margin-bottom: 14px !important;
        box-shadow: 0 4px 14px rgba(15,23,42,.10) !important;
        max-width: 100% !important;
    }
    .identity-row {
        display: grid !important;
        grid-template-columns: 130px minmax(0, 1fr) !important;
        gap: 12px !important;
        align-items: center !important;
        padding: 10px 0 !important;
        border-bottom: 1px solid #eef2f7 !important;
    }
    .identity-row:last-child {
        border-bottom: none !important;
    }
    .identity-label {
        color: #334155 !important;
        font-size: 16px !important;
        font-weight: 900 !important;
        line-height: 1.2 !important;
        white-space: nowrap !important;
    }
    .identity-company {
        color: #0f172a !important;
        font-size: clamp(22px, 2.1vw, 30px) !important;
        font-weight: 950 !important;
        line-height: 1.1 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        word-break: normal !important;
        overflow-wrap: normal !important;
        text-align: left !important;
    }
    .identity-ticker {
        color: #0b1f4d !important;
        font-size: clamp(26px, 2.5vw, 36px) !important;
        font-weight: 950 !important;
        line-height: 1.05 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        text-align: left !important;
    }
    @media (max-width: 720px) {
        .identity-row {
            grid-template-columns: 120px minmax(0, 1fr) !important;
            gap: 8px !important;
        }
        .identity-label {
            font-size: 15px !important;
        }
        .identity-company {
            font-size: 23px !important;
        }
        .identity-ticker {
            font-size: 30px !important;
        }
    }

    /* AI_STOCK_V21_DASHBOARD_UI_CSS */
    .block-container {
        padding-top: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 1180px !important;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #071a33 0%, #0b2748 100%) !important;
        border-right: 1px solid rgba(255,255,255,.08);
    }
    [data-testid="stSidebar"] * {
        color: #eaf2ff !important;
    }

    .app-hero {
        background: linear-gradient(135deg, #ffffff 0%, #f8fbff 62%, #edf6ff 100%);
        border: 1px solid #dfe7f1;
        border-radius: 18px;
        padding: 24px 30px;
        margin: 4px 0 22px 0;
        box-shadow: 0 8px 28px rgba(15, 23, 42, .10);
        display: flex;
        align-items: center;
        gap: 22px;
        position: relative;
        overflow: hidden;
    }
    .app-hero::after {
        content: "";
        position: absolute;
        right: 0;
        top: 0;
        width: 42%;
        height: 100%;
        background:
            linear-gradient(135deg, rgba(255,255,255,0) 0%, rgba(219,234,254,.65) 100%),
            repeating-linear-gradient(90deg, rgba(30,64,175,.08) 0 2px, transparent 2px 18px);
        opacity: .65;
        pointer-events: none;
    }
    .hero-icon {
        width: 72px;
        height: 72px;
        border-radius: 18px;
        background: linear-gradient(135deg, #0f2f57, #173e71);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 38px;
        font-weight: 900;
        box-shadow: 0 10px 24px rgba(15,47,87,.25);
        z-index: 1;
    }
    .hero-title-wrap {
        z-index: 1;
    }
    .hero-title-main {
        color: #0f172a;
        font-size: clamp(30px, 3.4vw, 48px);
        line-height: 1.05;
        font-weight: 950;
        letter-spacing: -0.03em;
    }
    .hero-sub-main {
        color: #64748b;
        font-size: 15px;
        font-weight: 700;
        margin-top: 10px;
    }

    .dashboard-top-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.35fr) minmax(280px, .95fr);
        gap: 22px;
        align-items: stretch;
        margin-bottom: 22px;
    }
    .right-tools-grid {
        display: grid;
        grid-template-rows: 1fr 1fr;
        gap: 22px;
    }
    .site-card {
        background: #ffffff;
        border: 1px solid #dfe7f1;
        border-radius: 18px;
        box-shadow: 0 8px 24px rgba(15,23,42,.08);
    }
    .identity-site-card {
        padding: 28px 32px;
        min-height: 230px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .identity-site-row {
        display: grid;
        grid-template-columns: 190px minmax(0,1fr);
        gap: 20px;
        align-items: center;
        padding: 22px 0;
    }
    .identity-site-row + .identity-site-row {
        border-top: 2px solid #e2e8f0;
    }
    .identity-site-label {
        color: #0f172a;
        font-size: 22px;
        font-weight: 950;
        white-space: nowrap;
    }
    .identity-site-value {
        color: #0f172a;
        font-size: clamp(34px, 4vw, 48px);
        font-weight: 950;
        line-height: 1.0;
        text-align: right;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        letter-spacing: -0.02em;
    }
    .identity-site-ticker {
        color: #0b1f4d;
        font-size: clamp(36px, 4.4vw, 54px);
        font-weight: 950;
        text-align: right;
        white-space: nowrap;
    }

    .search-site-card {
        padding: 26px 30px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .search-site-title {
        color: #0f172a;
        font-size: 22px;
        font-weight: 950;
        margin-bottom: 16px;
    }
    .search-site-box {
        border: 2px solid #cbd5e1;
        border-radius: 13px;
        padding: 15px 16px;
        color: #94a3b8;
        font-weight: 800;
        background: #ffffff;
        font-size: 16px;
    }
    .favorite-site-card {
        background: linear-gradient(135deg, #153a66 0%, #0f2f57 100%);
        color: #ffffff;
        border-radius: 18px;
        box-shadow: 0 10px 26px rgba(15,47,87,.22);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: 950;
        min-height: 100px;
        letter-spacing: .02em;
        border: 1px solid rgba(255,255,255,.18);
    }

    .info-site-card {
        padding: 28px 32px;
        margin-bottom: 22px;
    }
    .info-section {
        padding: 18px 0 22px 0;
        border-bottom: 2px solid #e2e8f0;
    }
    .info-section:last-child {
        border-bottom: none;
        padding-bottom: 6px;
    }
    .info-title {
        color: #0f172a;
        font-size: 24px;
        font-weight: 950;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .info-body {
        color: #334155;
        font-size: 17px;
        line-height: 1.75;
        font-weight: 650;
        padding-left: 44px;
    }
    .info-class-grid {
        color: #334155;
        font-size: 16px;
        line-height: 1.8;
        font-weight: 750;
        padding-left: 44px;
    }

    @media (max-width: 900px) {
        .dashboard-top-grid {
            grid-template-columns: 1fr;
        }
        .right-tools-grid {
            grid-template-rows: auto;
        }
        .identity-site-row {
            grid-template-columns: 1fr;
            gap: 8px;
        }
        .identity-site-value,
        .identity-site-ticker {
            text-align: left;
        }
    }

    /* AI_STOCK_V22_COMPACT_UI_CSS */
    .block-container {
        padding-top: 1.1rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1080px !important;
    }
    .app-hero {
        padding: 16px 22px !important;
        margin: 0 0 14px 0 !important;
        border-radius: 15px !important;
        min-height: 82px !important;
    }
    .hero-icon {
        width: 54px !important;
        height: 54px !important;
        border-radius: 14px !important;
        font-size: 28px !important;
    }
    .hero-title-main {
        font-size: clamp(26px, 2.8vw, 38px) !important;
    }
    .hero-sub-main {
        font-size: 13px !important;
        margin-top: 5px !important;
    }
    .dashboard-top-grid {
        grid-template-columns: minmax(0, 1.28fr) minmax(250px, .82fr) !important;
        gap: 14px !important;
        margin-bottom: 14px !important;
    }
    .right-tools-grid {
        gap: 12px !important;
    }
    .site-card {
        border-radius: 15px !important;
        box-shadow: 0 5px 18px rgba(15,23,42,.07) !important;
    }
    .identity-site-card {
        padding: 16px 22px !important;
        min-height: 150px !important;
    }
    .identity-site-row {
        grid-template-columns: 150px minmax(0,1fr) !important;
        gap: 14px !important;
        padding: 13px 0 !important;
    }
    .identity-site-label {
        font-size: 18px !important;
    }
    .identity-site-value {
        font-size: clamp(28px, 3.2vw, 38px) !important;
    }
    .identity-site-ticker {
        font-size: clamp(30px, 3.4vw, 42px) !important;
    }

    .search-real-card {
        background: #ffffff;
        border: 1px solid #dfe7f1;
        border-radius: 15px;
        box-shadow: 0 5px 18px rgba(15,23,42,.07);
        padding: 16px 20px 12px 20px;
        min-height: 92px;
        box-sizing: border-box;
    }
    .search-real-title {
        color: #0f172a;
        font-size: 18px;
        font-weight: 950;
        margin-bottom: 8px;
    }
    .search-real-card [data-testid="stTextInput"] label {
        display: none !important;
    }
    .search-real-card [data-testid="stTextInput"] {
        margin-bottom: 0 !important;
    }
    .search-real-card [data-testid="stTextInput"] input {
        border-radius: 11px !important;
        min-height: 42px !important;
        font-size: 15px !important;
        font-weight: 700 !important;
    }

    .favorite-site-card {
        min-height: 76px !important;
        font-size: 20px !important;
        border-radius: 15px !important;
    }
    .info-site-card {
        padding: 18px 24px !important;
        margin-bottom: 14px !important;
        border-radius: 15px !important;
    }
    .info-section {
        padding: 11px 0 13px 0 !important;
        border-bottom: 1.5px solid #e2e8f0 !important;
    }
    .info-title {
        font-size: 20px !important;
        margin-bottom: 8px !important;
        gap: 8px !important;
    }
    .info-body {
        font-size: 15px !important;
        line-height: 1.55 !important;
        padding-left: 34px !important;
    }
    .info-class-grid {
        font-size: 14px !important;
        line-height: 1.6 !important;
        padding-left: 34px !important;
    }
    .notice {
        padding: 9px 12px !important;
        margin-bottom: 10px !important;
        border-radius: 10px !important;
        font-size: 13px !important;
    }
    .metric-card {
        min-height: 78px !important;
        padding: 9px 11px !important;
        border-radius: 12px !important;
        margin-bottom: 8px !important;
    }
    .metric-label2 {
        font-size: 12px !important;
        margin-bottom: 4px !important;
    }
    .metric-value2 {
        font-size: clamp(18px, 2.2vw, 26px) !important;
    }
    .metric-sub {
        font-size: 11px !important;
        margin-top: 4px !important;
    }
    @media (max-width: 900px) {
        .dashboard-top-grid {
            grid-template-columns: 1fr !important;
        }
        .identity-site-row {
            grid-template-columns: 120px minmax(0,1fr) !important;
        }
    }

    /* AI_STOCK_V23_FINAL_ORDER_CSS */
    .block-container {
        padding-top: 1.0rem !important;
        padding-left: 1.35rem !important;
        padding-right: 1.35rem !important;
        max-width: 1080px !important;
    }

    .app-hero {
        padding: 14px 20px !important;
        margin: 0 0 12px 0 !important;
        border-radius: 14px !important;
        min-height: 76px !important;
    }
    .hero-icon {
        width: 52px !important;
        height: 52px !important;
        border-radius: 13px !important;
        font-size: 27px !important;
        flex-shrink: 0 !important;
    }
    .hero-title-main {
        font-size: clamp(25px, 2.6vw, 36px) !important;
        white-space: nowrap !important;
        overflow: visible !important;
    }
    .hero-sub-main {
        font-size: 12.5px !important;
        margin-top: 5px !important;
    }

    .site-card {
        border-radius: 14px !important;
        box-shadow: 0 5px 16px rgba(15,23,42,.065) !important;
    }

    .dashboard-top-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.28fr) minmax(250px, .82fr);
        gap: 14px;
        margin-bottom: 12px;
        align-items: stretch;
    }

    .identity-site-card {
        padding: 16px 20px !important;
        min-height: 148px !important;
    }
    .identity-site-row {
        grid-template-columns: 150px minmax(0, 1fr) 112px 92px !important;
        gap: 12px !important;
        padding: 12px 0 !important;
        align-items: center !important;
    }
    .identity-site-row.company-row {
        grid-template-columns: 150px minmax(0, 1fr) !important;
    }
    .identity-site-label {
        font-size: 17px !important;
        color: #0f172a !important;
    }
    .identity-site-value {
        font-size: clamp(25px, 2.8vw, 34px) !important;
        text-align: left !important;
    }
    .identity-site-ticker {
        font-size: clamp(27px, 3vw, 38px) !important;
        text-align: left !important;
    }
    .identity-category-label {
        color: #0f172a;
        font-size: 17px;
        font-weight: 950;
        white-space: nowrap;
        text-align: right;
    }
    .identity-category-pill {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #f0e6ff;
        color: #6d28d9;
        font-size: 14px;
        font-weight: 900;
        border-radius: 10px;
        padding: 7px 11px;
        white-space: nowrap;
    }

    .search-real-card {
        padding: 15px 18px 12px 18px !important;
        min-height: 94px !important;
    }
    .search-real-title {
        font-size: 17px !important;
        margin-bottom: 8px !important;
    }
    .search-input-fav-row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 142px;
        gap: 10px;
        align-items: end;
    }
    .search-input-fav-row [data-testid="stTextInput"] label {
        display: none !important;
    }
    .search-input-fav-row [data-testid="stTextInput"] input {
        min-height: 40px !important;
        border-radius: 10px !important;
        font-size: 14px !important;
        font-weight: 700 !important;
    }
    .favorite-mini-card {
        height: 40px;
        border: 1px solid #d9e1ec;
        border-radius: 10px;
        background: #ffffff;
        color: #0f172a;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-size: 13px;
        font-weight: 900;
        box-shadow: 0 3px 10px rgba(15,23,42,.055);
        white-space: nowrap;
    }
    .search-main-button {
        margin-top: 10px;
        height: 42px;
        border-radius: 10px;
        background: linear-gradient(135deg, #0f172a, #182843);
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        font-size: 16px;
        font-weight: 950;
        box-shadow: 0 6px 15px rgba(15,23,42,.16);
    }

    .info-site-card {
        padding: 0 !important;
        margin-bottom: 12px !important;
        border-radius: 14px !important;
        overflow: hidden !important;
    }
    .compact-info-card {
        background: #ffffff;
        border: 1px solid #dfe7f1;
        border-radius: 14px;
        box-shadow: 0 5px 16px rgba(15,23,42,.055);
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .compact-section-title {
        color: #0f172a;
        font-size: 18px;
        font-weight: 950;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .compact-section-body {
        color: #334155;
        font-size: 14px;
        line-height: 1.55;
        font-weight: 650;
        padding-left: 30px;
    }

    .auto-data-card, .chart-card {
        background: #ffffff;
        border: 1px solid #dfe7f1;
        border-radius: 14px;
        box-shadow: 0 5px 16px rgba(15,23,42,.055);
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .section-header-v23 {
        color: #0f172a;
        font-size: 18px;
        font-weight: 950;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .metric-card {
        min-height: 70px !important;
        padding: 8px 10px !important;
        border-radius: 11px !important;
        margin-bottom: 8px !important;
    }
    .metric-label2 {
        font-size: 11.5px !important;
        margin-bottom: 4px !important;
    }
    .metric-value2 {
        font-size: clamp(17px, 2vw, 23px) !important;
    }
    .metric-sub {
        font-size: 10.5px !important;
        margin-top: 3px !important;
    }
    .stPlotlyChart {
        margin-top: -6px !important;
    }

    @media (max-width: 900px) {
        .dashboard-top-grid {
            grid-template-columns: 1fr !important;
        }
        .identity-site-row,
        .identity-site-row.company-row {
            grid-template-columns: 120px minmax(0,1fr) !important;
        }
        .identity-category-label, .identity-category-pill {
            display: none !important;
        }
        .search-input-fav-row {
            grid-template-columns: 1fr !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# AI関連図
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

    category_map = {cat: list(tickers) for cat, tickers in base_categories}
    fav_names = {}
    for item in st.session_state.favorite_stocks:
        cat = item.get("category", "未分類") or "未分類"
        ticker = item.get("ticker", "").upper()
        fav_names[ticker] = item.get("company", "")
        if cat not in category_map:
            category_map[cat] = []
        if ticker and ticker not in category_map[cat]:
            category_map[cat].append(ticker)

    selected = selected_ticker.upper() if selected_ticker else ""
    blocks = []
    for cat, tickers in category_map.items():
        items = []
        for t in tickers:
            hit = df[(df["ticker"] == t) | (df["yf_ticker"] == t)]
            if not hit.empty:
                name = hit.iloc[0]["company"]
                display = hit.iloc[0]["ticker"]
            else:
                name = fav_names.get(t, "")
                display = t
            active = " active" if selected in [display.upper(), t.upper()] else ""
            items.append(f'<div class="node stock{active}">{display}<br><small>{name}</small></div>')
        blocks.append(f"<div class='branch'><div class='node category'>{cat}</div><div class='stocks'>{''.join(items)}</div></div>")

    return f"""
    <html><head><style>
    body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fafafa;margin:0;padding:10px;overflow-x:hidden;}}
    .map {{display:flex;flex-direction:column;gap:14px;align-items:center;overflow-x:hidden;padding:12px;border:1px solid #e5e7eb;border-radius:18px;background:white;box-sizing:border-box;width:100%;max-width:100%;}}
    .center {{width:100%;display:flex;align-items:center;justify-content:center;padding:4px 0 8px 0;position:sticky;top:0;background:white;z-index:5;border-bottom:1px solid #f1f5f9;}}
    .ai {{width:92px;height:92px;border-radius:24px;background:#111827;color:white;font-size:38px;font-weight:900;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px rgba(0,0,0,.18);}}
    .branches {{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;width:100%;max-width:100%;box-sizing:border-box;}}
    .branch {{border:1px solid #e5e7eb;border-radius:16px;padding:10px;background:#fff;min-width:0;box-sizing:border-box;}}
    .node.category {{font-weight:900;font-size:18px;border-bottom:3px solid #ff7ab6;display:inline-block;margin-bottom:8px;}}
    .stocks {{display:flex;flex-wrap:wrap;gap:8px;}}
    .node.stock {{border:1px solid #d1d5db;border-radius:12px;padding:8px 10px;width:calc(50% - 4px);box-sizing:border-box;background:#f9fafb;font-weight:900;line-height:1.15;overflow:hidden;text-overflow:ellipsis;}}
    .node.stock small {{display:block;font-weight:500;color:#555;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
    .node.stock.active {{background:#fff7d6;border:3px solid #f59e0b;transform:scale(1.01);}}
    @media (max-width:760px) {{.branches {{grid-template-columns:1fr;}} .node.stock {{width:100%;}} .ai {{width:82px;height:82px;font-size:34px;}}}}

    .small-label {color:#cbd5e1;font-size:13px;font-weight:800;margin-top:6px;margin-bottom:2px;}
    .hero-company-main {font-size:34px;font-weight:900;line-height:1.05;color:white;margin-bottom:14px;word-break:break-word;}
    .hero-ticker-code {font-size:42px;font-weight:900;line-height:1.0;color:white;margin-bottom:12px;}

    .identity-box {
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.22);
        border-radius: 18px;
        padding: 16px 18px;
        margin-bottom: 14px;
    }
    .identity-label {
        color: #ffffff !important;
        font-size: 15px;
        font-weight: 900;
        letter-spacing: .03em;
        opacity: 0.96;
        margin-bottom: 6px;
    }
    .identity-company {
        color: #ffffff !important;
        font-size: 38px;
        font-weight: 950;
        line-height: 1.08;
        margin-bottom: 18px;
        text-shadow: 0 2px 10px rgba(0,0,0,.28);
        word-break: break-word;
    }
    .identity-ticker {
        color: #ffffff !important;
        font-size: 46px;
        font-weight: 950;
        line-height: 1.0;
        margin-bottom: 6px;
        text-shadow: 0 2px 10px rgba(0,0,0,.28);
    }
    </style></head><body>
    <div class="map"><div class="center"><div class="ai">AI</div></div><div class="branches">{''.join(blocks)}</div></div>
    </body></html>
    """

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
    cols = st.columns(3)
    for i, (label, url) in enumerate(make_external_links(row)):
        with cols[i % 3]:
            st.link_button(label, url, use_container_width=True)

def show_source_table(source_map):
    labels = [
        ("会社名", "company"), ("分類", "sector"), ("業種", "industry"), ("事業内容", "description"),
        ("株価", "price"), ("前日終値", "prev_close"), ("前日比", "change_pct"),
        ("時価総額", "market_cap"), ("PER", "per"), ("予想PER", "forward_pe"), ("PBR", "pbr"),
        ("52週高値", "fifty_two_high"), ("52週安値", "fifty_two_low"), ("配当利回り", "dividend_yield"),
    ]
    st.dataframe(
        pd.DataFrame([{"項目": label, "取得元": source_map.get(key, "未取得")} for label, key in labels]),
        use_container_width=True,
        hide_index=True,
    )

def show_register_box(row):
    categories = sorted(set(
        df["category"].dropna().astype(str).tolist()
        + [x["category"] for x in st.session_state.favorite_stocks]
        + ["GPU", "メモリー", "冷却", "電力", "原子力", "光通信", "データセンター", "半導体製造装置", "素材", "日本AI関連", "未分類"]
        + [row["category"]]
    ))
    default_index = categories.index(row["category"]) if row["category"] in categories else 0

    st.subheader("⭐ AI関連図に登録")
    c1, c2 = st.columns([2, 2])
    with c1:
        selected = st.selectbox("登録カテゴリ", categories, index=default_index, key=f"reg_cat_{row['ticker']}")
    with c2:
        custom = st.text_input("新カテゴリ名", value="", key=f"reg_custom_{row['ticker']}", placeholder="例：AI通信・クラウド")
    final_cat = custom.strip() if custom.strip() else selected

    if st.button("この銘柄をAI関連図に登録", key=f"reg_btn_{row['ticker']}", use_container_width=True):
        add_favorite_stock(row["ticker"], row["company"], final_cat)
        st.success(f'{row["ticker"]} を「{final_cat}」に登録しました。左メニューの「AI関連図」で確認できます。')

    if bool(row.get("_virtual", False)):
        st.markdown("### 📋 stocks.csvに追加する行")
        sample = f'{row["ticker"]},{row["yf_ticker"]},{row["company"]},{final_cat},{row["business"]},{row["ai_relation"]},{row["ai_score"]},{row["keywords"]},"",'
        st.code(sample, language="csv")

def show_stock_page(row):
    combined, source_map = get_combined_data(row["yf_ticker"], FMP_API_KEY, ALPHAVANTAGE_API_KEY, FINNHUB_API_KEY)

    display_category = row.get("category", "未分類") or "未分類"
    display_industry = combined.get("industry") or ""
    display_business = translate_to_japanese(row.get("business", ""))
    display_relation = row.get("ai_relation", "")

    # 未登録銘柄の場合は、API取得情報を優先
    if bool(row.get("_virtual", False)):
        display_category = combined.get("sector") or row.get("category", "未分類")
        display_industry = combined.get("industry") or ""
        raw_business = combined.get("description") or row.get("business", "")
        display_business = trim_text(translate_to_japanese(raw_business), 520)
        display_relation = auto_ai_relation(display_category, display_industry, display_business)

    display_company_name = clean_company_name(row["company"]) or row["ticker"]

    top_left, top_right = st.columns([1.28, 0.82], gap="medium")

    with top_left:
        st.markdown(
            f"""
            <div class="site-card identity-site-card">
                <div class="identity-site-row company-row">
                    <div class="identity-site-label">会社名</div>
                    <div class="identity-site-value">{display_company_name}</div>
                </div>
                <div class="identity-site-row">
                    <div class="identity-site-label">ティッカーコード</div>
                    <div class="identity-site-ticker">{row["ticker"]}</div>
                    <div class="identity-category-label">分類</div>
                    <div class="identity-category-pill">{display_category or "未取得"}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_right:
        st.markdown('<div class="search-real-card"><div class="search-real-title">🔎 ティッカーコード検索</div><div class="search-input-fav-row">', unsafe_allow_html=True)

        input_col, fav_col = st.columns([1.0, 0.52], gap="small")
        with input_col:
            st.text_input(
                "ティッカーコード検索",
                key="ticker_search_input",
                on_change=sync_ticker_input,
                placeholder="例：AAPL",
            )
        with fav_col:
            st.markdown('<div class="favorite-mini-card">☆ お気に入り登録</div>', unsafe_allow_html=True)

        st.markdown('</div><div class="search-main-button">🔍　検索</div></div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="compact-info-card">
            <div class="compact-section-title">🏢 何を作るか / 事業内容</div>
            <div class="compact-section-body">{display_business}</div>
        </div>
        <div class="compact-info-card">
            <div class="compact-section-title">🔗 AIとのつながり</div>
            <div class="compact-section-body">{display_relation}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if bool(row.get("_virtual", False)):
        st.markdown(
            """
            <div class="notice">
            <b>未登録銘柄です。</b><br>
            無料API/yfinanceから取得できた会社名・分類・業種・事業内容を自動反映しています。
            APIキーを追加すると、より詳細な情報が出やすくなります。
            </div>
            """,
            unsafe_allow_html=True,
        )

    show_external_links(row)
    show_register_box(row)

    st.markdown('<div class="auto-data-card"><div class="section-header-v23">▦ 自動取得データ</div>', unsafe_allow_html=True)
    if not FMP_API_KEY and not ALPHAVANTAGE_API_KEY and not FINNHUB_API_KEY:
        st.markdown(
            """
            <div class="notice">
            現在は <b>yfinanceのみ</b> で取得しています。<br>
            FMP_API_KEY / ALPHAVANTAGE_API_KEY / FINNHUB_API_KEY を Secrets に入れると、会社概要・PER/PBR/時価総額の補完ができます。
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        active = []
        if FMP_API_KEY: active.append("FMP")
        if FINNHUB_API_KEY: active.append("Finnhub")
        if ALPHAVANTAGE_API_KEY: active.append("Alpha Vantage")
        st.markdown(f'<div class="safe">補助APIが有効です：<b>{", ".join(active)}</b></div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: metric_card("株価", fmt_price(combined["price"], combined["currency"]), delta_text(combined["change_pct"]))
    with c2: metric_card("時価総額", fmt_market_cap(combined["market_cap"]), f'取得元：{source_map.get("market_cap")}')
    with c3: metric_card("PER", fmt_num(combined["per"]), f'取得元：{source_map.get("per")}')
    with c4: metric_card("予想PER", fmt_num(combined["forward_pe"]), f'取得元：{source_map.get("forward_pe")}')
    with c5: metric_card("PBR", fmt_num(combined["pbr"]), f'取得元：{source_map.get("pbr")}')

    dy = None
    if combined["dividend_yield"] is not None:
        try:
            dy = float(combined["dividend_yield"]) * 100 if float(combined["dividend_yield"]) < 1 else float(combined["dividend_yield"])
        except Exception:
            dy = combined["dividend_yield"]

    c6, c7, c8, c9 = st.columns(4)
    with c6: metric_card("前日終値", fmt_price(combined["prev_close"], combined["currency"]), f'取得元：{source_map.get("prev_close")}')
    with c7: metric_card("52週高値", fmt_price(combined["fifty_two_high"], combined["currency"]), f'取得元：{source_map.get("fifty_two_high")}')
    with c8: metric_card("52週安値", fmt_price(combined["fifty_two_low"], combined["currency"]), f'取得元：{source_map.get("fifty_two_low")}')
    with c9: metric_card("配当利回り", fmt_percent(dy), f'取得元：{source_map.get("dividend_yield")}')

    with st.expander("📌 取得元を確認する"):
        show_source_table(source_map)

    st.caption("※ 自動取得データは参考値です。無料API/yfinanceは欠損・遅延・制限があります。投資判断は自己責任でお願いします。")

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="chart-card"><div class="section-header-v23">📈 株価チャート</div>', unsafe_allow_html=True)
    hist = get_yf_history(row["yf_ticker"], period_map[period_label])
    if hist.empty:
        st.warning("チャートデータを取得できませんでした。")
    else:
        date_col = "Date" if "Date" in hist.columns else hist.columns[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist[date_col], y=hist["Close"], mode="lines", name="Close"))
        fig.update_layout(height=380, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------
# UI
# -----------------------------
st.markdown(
    '''
    <div class="app-hero">
        <div class="hero-icon">📖</div>
        <div class="hero-title-wrap">
            <div class="hero-title-main">AI関連株コード辞典 v23</div>
            <div class="hero-sub-main">会社情報・AIとのつながり・分類を見やすく整理するリサーチ画面</div>
        </div>
    </div>
    ''',
    unsafe_allow_html=True,
)

st.sidebar.title("🔎 操作メニュー")
mode = st.sidebar.radio("表示モード", ["ティッカー検索", "キーワード検索", "カテゴリ表示", "AI関連図", "全銘柄一覧", "API設定確認"])
period_label = st.sidebar.selectbox("チャート期間", ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"], index=2)
st.sidebar.markdown("---")
st.sidebar.caption("米国株例：NVDA / AAPL / MSFT / D / T")
st.sidebar.caption("日本株例：7203.T / 9984.T / 6857.T")

if mode == "ティッカー検索":
    ticker = st.session_state.get("last_ticker", "NVDA").strip().upper()
    row = build_row_from_ticker(ticker)
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
            st.warning("該当する登録済み銘柄がありません。")
        else:
            st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

elif mode == "カテゴリ表示":
    category = st.selectbox("カテゴリを選択", sorted(df["category"].dropna().unique().tolist()))
    result = df[df["category"] == category]
    st.subheader(f"カテゴリ：{category}")
    st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

elif mode == "AI関連図":
    st.subheader("🗺 AI関連図")
    components.html(make_mindmap_html(), height=980, scrolling=False)
    st.subheader("⭐ 登録済みお気に入り")
    fav_df = pd.DataFrame(st.session_state.favorite_stocks)
    if fav_df.empty:
        st.info("まだ登録された銘柄はありません。ティッカー検索から登録できます。")
    else:
        st.dataframe(fav_df, use_container_width=True, hide_index=True)
        target = st.selectbox("解除する銘柄", fav_df["ticker"].tolist())
        if st.button("選択した銘柄を解除", use_container_width=True):
            remove_favorite_stock(target)
            st.success(f"{target} を解除しました。")

elif mode == "全銘柄一覧":
    st.subheader("登録銘柄一覧")
    st.dataframe(df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "official_ir_url"]], use_container_width=True, hide_index=True)

elif mode == "API設定確認":
    st.subheader("API設定確認")
    st.write("FMP_API_KEY:", "設定済み" if FMP_API_KEY else "未設定")
    st.write("FINNHUB_API_KEY:", "設定済み" if FINNHUB_API_KEY else "未設定")
    st.write("ALPHAVANTAGE_API_KEY:", "設定済み" if ALPHAVANTAGE_API_KEY else "未設定")
    st.markdown(
        """
        ### Streamlit Cloudで設定する場所
        App管理画面 → Settings → Secrets

        ```toml
        FMP_API_KEY = "ここにFMPのAPIキー"
        FINNHUB_API_KEY = "ここにFinnhubのAPIキー"
        ALPHAVANTAGE_API_KEY = "ここにAlpha VantageのAPIキー"
        ```

        会社概要・業種・事業内容は、APIキーを入れるほど出やすくなります。
        """
    )

st.markdown("---")
with st.expander("🛠 銘柄データの追加・修正方法"):
    st.markdown(
        """
        `stocks.csv` に1行追加します。

        大事な列：
        - `ticker`：表示用ティッカー
        - `yf_ticker`：yfinance取得用コード。日本株は例：`7203.T`
        - `company`：会社名
        - `category`：分類
        - `business`：事業内容
        - `ai_relation`：AIとのつながり
        - `ai_score`：1〜5
        - `keywords`：検索用キーワード
        - `related`：関連銘柄。カンマ区切り
        - `official_ir_url`：公式IRページ
        """
    )
