
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
from pathlib import Path
from urllib.parse import quote_plus
import requests
import yfinance as yf
import json

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

st.set_page_config(page_title="AI関連株コード辞典 v44", page_icon="📈", layout="wide")

# ============================================================
# AI関連株コード辞典 v44 Clean
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
# お気に入り登録 → 登録銘柄一覧へ追加表示する一時DB
# 注意：Streamlitのセッション内保存。アプリ再起動で消える可能性あり。
# -----------------------------
REGISTER_COLS = [
    "ticker", "yf_ticker", "company", "category", "business",
    "ai_relation", "ai_score", "keywords", "related", "official_ir_url"
]

if "registered_extra_stocks" not in st.session_state:
    st.session_state.registered_extra_stocks = []

if "google_sheet_last_error" not in st.session_state:
    st.session_state.google_sheet_last_error = ""

if "return_to_mode" not in st.session_state:
    st.session_state.return_to_mode = ""

def get_registered_extra_df():
    if not st.session_state.registered_extra_stocks:
        return pd.DataFrame(columns=REGISTER_COLS)
    out = pd.DataFrame(st.session_state.registered_extra_stocks)
    for col in REGISTER_COLS:
        if col not in out.columns:
            out[col] = ""
    return out[REGISTER_COLS]

def get_all_registered_df():
    base = df.copy()
    google_df = load_google_sheet_stocks() if "load_google_sheet_stocks" in globals() else pd.DataFrame(columns=REGISTER_COLS)
    extra = get_registered_extra_df()

    parts = [base[REGISTER_COLS]]
    if not google_df.empty:
        parts.append(google_df[REGISTER_COLS])
    if not extra.empty:
        parts.append(extra[REGISTER_COLS])

    combined = pd.concat(parts, ignore_index=True)
    combined["ticker"] = combined["ticker"].astype(str).str.upper()
    combined["yf_ticker"] = combined["yf_ticker"].astype(str).str.upper()
    combined = combined.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)
    return combined


def get_persistent_favorites_df():
    """Google Sheetsとセッション一時登録から、AI関連図へ戻す銘柄だけを取得する。"""
    parts = []
    try:
        google_df = load_google_sheet_stocks()
        if not google_df.empty:
            parts.append(google_df[REGISTER_COLS])
    except Exception:
        pass

    try:
        extra = get_registered_extra_df()
        if not extra.empty:
            parts.append(extra[REGISTER_COLS])
    except Exception:
        pass

    if not parts:
        return pd.DataFrame(columns=REGISTER_COLS)

    out = pd.concat(parts, ignore_index=True)
    for col in REGISTER_COLS:
        if col not in out.columns:
            out[col] = ""
    out = out[REGISTER_COLS]
    out["ticker"] = out["ticker"].astype(str).str.upper()
    out["yf_ticker"] = out["yf_ticker"].astype(str).str.upper()
    out = out.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)
    return out


def normalize_display_category(value):
    """全銘柄一覧ではカテゴリ表示を1つにまとめる。"""
    s = str(value or "未分類").strip()
    if not s:
        return "未分類"
    # "A / B" のような複合分類は一番左を主カテゴリとして表示
    if " / " in s:
        s = s.split(" / ")[0].strip()
    # "A｜B" や "A,B" のような入力も1つ目だけ表示
    for sep in ["｜", "|", ",", "、"]:
        if sep in s:
            s = s.split(sep)[0].strip()
    return s or "未分類"

def open_ticker_from_button(ticker, return_to="全銘柄一覧"):
    """一覧やAI関連図からティッカー検索ページへ移動する。"""
    t = str(ticker or "").upper().strip()
    if not t:
        return
    st.session_state.last_ticker = t
    st.session_state.display_mode = "ティッカー検索"
    st.session_state.return_to_mode = return_to
    if "display_mode_radio" in st.session_state:
        try:
            del st.session_state["display_mode_radio"]
        except Exception:
            pass
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()

def return_to_previous_mode():
    """ティッカー検索から元の画面へ戻る。"""
    target = st.session_state.get("return_to_mode", "")
    if target not in ["全銘柄一覧", "AI関連図"]:
        target = "全銘柄一覧"
    st.session_state.display_mode = target
    st.session_state.return_to_mode = ""
    if "display_mode_radio" in st.session_state:
        try:
            del st.session_state["display_mode_radio"]
        except Exception:
            pass
    st.rerun()

def apply_query_open_ticker():
    """AI関連図HTMLのリンク ?open_ticker=XXX からティッカー検索へ移動する。"""
    try:
        q = st.query_params
        t = q.get("open_ticker", "")
        src = q.get("from", "")
        if isinstance(t, list):
            t = t[0] if t else ""
        if isinstance(src, list):
            src = src[0] if src else ""
        t = str(t or "").upper().strip()
        src = str(src or "").strip()
        if t:
            st.session_state.last_ticker = t
            st.session_state.display_mode = "ティッカー検索"
            st.session_state.return_to_mode = "AI関連図" if src == "ai" else "全銘柄一覧"
            if "display_mode_radio" in st.session_state:
                try:
                    del st.session_state["display_mode_radio"]
                except Exception:
                    pass
            try:
                st.query_params.clear()
            except Exception:
                pass
    except Exception:
        pass

def add_registered_extra_stock(row, category=None):
    ticker = str(row.get("ticker", "")).upper().strip()
    if not ticker:
        return False

    final_category = str(category or row.get("category", "未分類") or "未分類").strip()
    score_value = row.get("ai_score", 3)
    try:
        score_value = int(score_value)
    except Exception:
        score_value = 3

    item = {
        "ticker": ticker,
        "yf_ticker": str(row.get("yf_ticker", ticker)).upper().strip(),
        "company": str(row.get("company", ticker)).strip(),
        "category": final_category,
        "business": str(row.get("business", "")).strip(),
        "ai_relation": str(row.get("ai_relation", "")).strip(),
        "ai_score": score_value,
        "keywords": str(row.get("keywords", "")).strip(),
        "related": str(row.get("related", "")).strip(),
        "official_ir_url": str(row.get("official_ir_url", "")).strip(),
    }

    replaced = False
    for i, old in enumerate(st.session_state.registered_extra_stocks):
        if str(old.get("ticker", "")).upper() == ticker:
            st.session_state.registered_extra_stocks[i] = item
            replaced = True
            break
    if not replaced:
        st.session_state.registered_extra_stocks.append(item)

    return True

def remove_registered_extra_stock(ticker):
    ticker = str(ticker).upper().strip()
    st.session_state.registered_extra_stocks = [
        x for x in st.session_state.registered_extra_stocks
        if str(x.get("ticker", "")).upper() != ticker
    ]

def build_csv_line_from_row(row, category=None):
    final_category = str(category or row.get("category", "未分類") or "未分類")
    values = [
        row.get("ticker", ""),
        row.get("yf_ticker", row.get("ticker", "")),
        row.get("company", ""),
        final_category,
        row.get("business", ""),
        row.get("ai_relation", ""),
        row.get("ai_score", 3),
        row.get("keywords", ""),
        row.get("related", ""),
        row.get("official_ir_url", ""),
    ]
    def clean(v):
        s = str(v).replace("\n", " ").replace("\r", " ").strip()
        if "," in s or '"' in s:
            s = '"' + s.replace('"', '""') + '"'
        return s
    return ",".join(clean(v) for v in values)


# -----------------------------
# Googleスプレッドシート永久保存
# Streamlit Secretsに GOOGLE_SHEET_ID と gcp_service_account を設定すると有効
# -----------------------------
def google_sheet_enabled():
    try:
        return bool(st.secrets.get("GOOGLE_SHEET_ID", "")) and gspread is not None and Credentials is not None
    except Exception:
        return False

def get_google_sheet_id():
    try:
        return st.secrets.get("GOOGLE_SHEET_ID", "")
    except Exception:
        return ""

def get_service_account_info():
    try:
        if "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
        else:
            raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
            info = json.loads(raw) if raw else None

        if not info:
            return None

        pk = info.get("private_key", "")
        if isinstance(pk, str):
            pk = pk.replace("\\n", "\n").strip()
            if "-----BEGIN PRIVATE KEY-----" in pk and not pk.endswith("\n"):
                pk += "\n"
            info["private_key"] = pk

        return info
    except Exception as e:
        try:
            st.session_state.google_sheet_last_error = f"サービスアカウント情報の読み込みエラー：{e}"
        except Exception:
            pass
        return None

def get_gspread_worksheet():
    try:
        if not google_sheet_enabled():
            st.session_state.google_sheet_last_error = "GOOGLE_SHEET_ID / gcp_service_account / gspread のいずれかが未設定です。"
            return None

        info = get_service_account_info()
        if not info:
            st.session_state.google_sheet_last_error = "gcp_service_account が読み取れません。Secretsを確認してください。"
            return None

        sheet_id = str(get_google_sheet_id()).strip()
        if not sheet_id:
            st.session_state.google_sheet_last_error = "GOOGLE_SHEET_ID が空です。"
            return None

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open_by_key(sheet_id)
        except Exception as e:
            email = str(info.get("client_email", ""))
            st.session_state.google_sheet_last_error = (
                f"スプレッドシートを開けません：{type(e).__name__} / {str(e) or repr(e)} / "
                f"sheet_id={sheet_id[:6]}...{sheet_id[-6:]} / client_email={email}"
            )
            return None

        try:
            ws = spreadsheet.worksheet("stocks")
        except Exception:
            try:
                ws = spreadsheet.add_worksheet(title="stocks", rows=1000, cols=len(REGISTER_COLS))
            except Exception as e:
                st.session_state.google_sheet_last_error = f"stocksシート作成エラー：{type(e).__name__} / {str(e) or repr(e)}"
                return None

        try:
            header = ws.row_values(1)
            if not header:
                ws.append_row(REGISTER_COLS)
            elif header[:len(REGISTER_COLS)] != REGISTER_COLS:
                ws.update("A1:J1", [REGISTER_COLS])
        except Exception as e:
            st.session_state.google_sheet_last_error = f"ヘッダー確認エラー：{type(e).__name__} / {str(e) or repr(e)}"
            return None

        st.session_state.google_sheet_last_error = ""
        return ws

    except Exception as e:
        st.session_state.google_sheet_last_error = f"Googleスプレッドシート接続エラー：{type(e).__name__} / {str(e) or repr(e)}"
        return None

def load_google_sheet_stocks():
    try:
        ws = get_gspread_worksheet()
        if ws is None:
            return pd.DataFrame(columns=REGISTER_COLS)

        values = ws.get_all_values()
        if not values:
            return pd.DataFrame(columns=REGISTER_COLS)

        rows = values[1:]
        normalized_rows = []
        for row in rows:
            if not any(str(x).strip() for x in row):
                continue
            row = list(row) + [""] * (len(REGISTER_COLS) - len(row))
            normalized_rows.append(row[:len(REGISTER_COLS)])

        if not normalized_rows:
            return pd.DataFrame(columns=REGISTER_COLS)

        out = pd.DataFrame(normalized_rows, columns=REGISTER_COLS)
        out["ticker"] = out["ticker"].astype(str).str.upper()
        out["yf_ticker"] = out["yf_ticker"].astype(str).str.upper()
        return out

    except Exception as e:
        st.session_state.google_sheet_last_error = f"Google保存読み込みエラー：{type(e).__name__} / {str(e) or repr(e)}"
        return pd.DataFrame(columns=REGISTER_COLS)

def save_stock_to_google_sheet(row, category=None):
    try:
        ws = get_gspread_worksheet()
    except Exception as e:
        msg = f"Googleスプレッドシート接続エラー：{type(e).__name__} / {str(e) or repr(e)}"
        st.session_state.google_sheet_last_error = msg
        return False, msg

    if ws is None:
        msg = st.session_state.get("google_sheet_last_error", "")
        if not msg:
            msg = "Googleスプレッドシートに接続できません。API設定確認の接続エラーを確認してください。"
        return False, msg

    ticker = str(row.get("ticker", "")).upper().strip()
    if not ticker:
        return False, "ティッカーが空です"

    final_category = str(category or row.get("category", "未分類") or "未分類")
    values = [
        ticker,
        str(row.get("yf_ticker", ticker)).upper().strip(),
        str(row.get("company", ticker)).strip(),
        final_category,
        str(row.get("business", "")).replace("\n", " ").replace("\r", " ").strip(),
        str(row.get("ai_relation", "")).replace("\n", " ").replace("\r", " ").strip(),
        str(row.get("ai_score", 3)),
        str(row.get("keywords", "")).replace("\n", " ").replace("\r", " ").strip(),
        str(row.get("related", "")).replace("\n", " ").replace("\r", " ").strip(),
        str(row.get("official_ir_url", "")).strip(),
    ]

    try:
        # ヘッダー確認。空なら作る。
        try:
            header = ws.row_values(1)
            if not header:
                ws.append_row(REGISTER_COLS)
            elif header[:len(REGISTER_COLS)] != REGISTER_COLS:
                ws.update("A1:J1", [REGISTER_COLS])
        except Exception:
            pass

        tickers = [str(x).upper().strip() for x in ws.col_values(1)]

        if ticker in tickers:
            row_no = tickers.index(ticker) + 1
            ws.update(f"A{row_no}:J{row_no}", [values])
            st.session_state.google_sheet_last_error = ""
            return True, "Googleスプレッドシートの既存行を更新しました"
        else:
            # append_rowで失敗する環境もあるので、次の空行にupdateする方式に変更
            next_row = len(tickers) + 1
            if next_row < 2:
                next_row = 2
            ws.update(f"A{next_row}:J{next_row}", [values])
            st.session_state.google_sheet_last_error = ""
            return True, "Googleスプレッドシートに追加しました"

    except Exception as e:
        msg = f"保存エラー：{type(e).__name__} / {str(e) or repr(e)}"
        st.session_state.google_sheet_last_error = msg
        return False, msg

def delete_stock_from_google_sheet(ticker):
    try:
        ws = get_gspread_worksheet()
    except Exception as e:
        return False, f"Googleスプレッドシート接続エラー：{e}"
    if ws is None:
        return False, st.session_state.get("google_sheet_last_error", "Googleスプレッドシート未設定")

    ticker = str(ticker).upper().strip()
    try:
        tickers = [x.upper() for x in ws.col_values(1)]
        if ticker in tickers:
            row_no = tickers.index(ticker) + 1
            if row_no > 1:
                ws.delete_rows(row_no)
                load_google_sheet_stocks.clear()
                return True, f"{ticker} をGoogleスプレッドシートから削除しました"
        return False, "対象銘柄が見つかりません"
    except Exception as e:
        return False, f"削除エラー：{e}"

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


def fmt_date_value(x):
    if x is None or x == "" or (hasattr(pd, "isna") and not isinstance(x, (list, dict, pd.DataFrame)) and pd.isna(x)):
        return "未取得"
    try:
        if hasattr(x, "strftime"):
            return x.strftime("%Y/%m/%d")
        return str(x)[:10]
    except Exception:
        return str(x)

def fmt_news_title(x):
    x = str(x or "").strip()
    if not x:
        return "未取得"
    if len(x) > 34:
        return x[:34] + "..."
    return x

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
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None, "eps": None, "roe": None, "earnings_date": None, "news_headline": None,
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
            result["eps"] = pick_first(info.get("trailingEps"), info.get("epsTrailingTwelveMonths"), info.get("forwardEps"))
            result["roe"] = pick_first(info.get("returnOnEquity"))
            result["earnings_date"] = pick_first(info.get("earningsDate"), info.get("mostRecentQuarter"))
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

        try:
            cal = t.calendar
            if cal is not None:
                if isinstance(cal, pd.DataFrame) and not cal.empty:
                    for key in ["Earnings Date", "Earnings Average", "Earnings Low", "Earnings High"]:
                        if key in cal.index:
                            val = cal.loc[key].dropna()
                            if len(val) > 0:
                                result["earnings_date"] = pick_first(result["earnings_date"], val.iloc[0])
                                break
                elif isinstance(cal, dict):
                    ed = pick_first(cal.get("Earnings Date"), cal.get("EarningsDate"), cal.get("earningsDate"))
                    if isinstance(ed, (list, tuple)) and len(ed) > 0:
                        ed = ed[0]
                    result["earnings_date"] = pick_first(result["earnings_date"], ed)
        except Exception:
            pass

        try:
            news = getattr(t, "news", None)
            if news:
                first = news[0]
                title = pick_first(first.get("title"), first.get("content", {}).get("title") if isinstance(first.get("content"), dict) else None)
                result["news_headline"] = pick_first(result["news_headline"], title)
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
        "fifty_two_high": None, "fifty_two_low": None, "dividend_yield": None, "eps": None, "roe": None, "earnings_date": None, "news_headline": None,
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
        "fifty_two_high", "fifty_two_low", "dividend_yield", "eps", "roe", "earnings_date", "news_headline", "currency",
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
    all_df = get_all_registered_df()
    hit = all_df[(all_df["ticker"].str.upper() == t) | (all_df["yf_ticker"].str.upper() == t)]
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
        margin: 10px 0 16px 0 !important;
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

    /* AI_STOCK_V24_REFERENCE_UI_CSS */
    .block-container {
        max-width: 1220px !important;
        padding-top: 0.85rem !important;
        padding-left: 1.4rem !important;
        padding-right: 1.4rem !important;
        padding-bottom: 2rem !important;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #051630 0%, #092652 100%) !important;
        border-right: 1px solid rgba(255,255,255,.06);
    }
    [data-testid="stSidebar"] * {
        color: #eef4ff !important;
    }
    .sidebar-brand {
        background: linear-gradient(180deg, rgba(255,255,255,.06) 0%, rgba(255,255,255,.02) 100%);
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 18px;
        padding: 16px 16px 14px 16px;
        margin-bottom: 16px;
        box-shadow: 0 12px 24px rgba(0,0,0,.16);
    }
    .sidebar-brand-top {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 10px;
    }
    .sidebar-logo {
        width: 46px;
        height: 46px;
        border-radius: 12px;
        background: linear-gradient(135deg, #ffffff, #e7eefc);
        color: #0b3a86;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 23px;
        font-weight: 900;
        box-shadow: 0 8px 18px rgba(0,0,0,.20);
    }
    .sidebar-brand-title {
        font-size: 18px;
        font-weight: 950;
        line-height: 1.25;
        color: #ffffff;
    }
    .sidebar-brand-sub {
        color: #d6e5ff;
        font-size: 12.6px;
        line-height: 1.55;
        font-weight: 700;
    }
    .sidebar-note {
        background: rgba(255,255,255,.06);
        border: 1px solid rgba(255,255,255,.06);
        border-radius: 16px;
        padding: 14px 14px;
        margin-top: 16px;
        color: #dce9ff;
        font-size: 12.4px;
        line-height: 1.7;
        font-weight: 700;
    }
    .sidebar-menu-label {
        font-size: 12px;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
        color: #b7cffb;
        margin: 8px 0 2px 0;
    }

    .app-hero {
        background: linear-gradient(135deg, #ffffff 0%, #f9fbff 65%, #eef6ff 100%);
        border: 1px solid #dce6f2;
        border-radius: 18px;
        padding: 16px 22px !important;
        margin: 10px 0 16px 0 !important;
        box-shadow: 0 8px 24px rgba(15,23,42,.06);
        display: flex;
        align-items: center;
        gap: 18px;
        overflow: visible !important;
        min-height: 76px;
    }
    .app-hero::after {
        content: "";
        position: absolute;
        inset: 0;
        border-radius: 18px;
        pointer-events: none;
        background:
            linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(218,234,255,.32) 100%),
            repeating-linear-gradient(90deg, rgba(37,99,235,.05) 0 1px, transparent 1px 16px);
        opacity: .7;
    }
    .hero-icon {
        width: 58px !important;
        height: 58px !important;
        border-radius: 14px !important;
        font-size: 28px !important;
        background: linear-gradient(135deg, #0d3c8d, #1d4ed8) !important;
        flex-shrink: 0;
        z-index: 1;
    }
    .hero-title-wrap {
        z-index: 1;
    }
    .hero-title-main {
        color: #0f172a !important;
        font-size: clamp(26px, 2.8vw, 40px) !important;
        line-height: 1.18 !important;
        font-weight: 950 !important;
        letter-spacing: -0.02em;
        white-space: nowrap;
        overflow: visible !important;
    }
    .hero-sub-main {
        color: #475569 !important;
        font-size: 13.2px !important;
        font-weight: 700 !important;
        margin-top: 6px !important;
        line-height: 1.45 !important;
    }

    .site-card {
        background: #ffffff;
        border: 1px solid #dbe4ef;
        border-radius: 16px;
        box-shadow: 0 5px 16px rgba(15,23,42,.05);
    }
    .top-section-card, .search-panel-card, .section-card, .auto-data-card, .chart-card {
        margin-bottom: 14px;
    }
    .top-section-card, .search-panel-card {
        padding: 16px 18px;
    }
    .section-card, .auto-data-card, .chart-card {
        padding: 14px 16px;
    }

    .card-head {
        color: #0f172a;
        font-size: 17px;
        font-weight: 950;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .identity-table {
        border: 1px solid #e4e9f0;
        border-radius: 12px;
        overflow: hidden;
        background: #fcfdff;
    }
    .identity-row {
        display: grid;
        gap: 12px;
        padding: 14px 16px;
        align-items: center;
    }
    .identity-row + .identity-row {
        border-top: 1px solid #e9eef5;
    }
    .identity-row.company {
        grid-template-columns: 160px minmax(0, 1fr);
    }
    .identity-row.ticker {
        grid-template-columns: 160px minmax(0, 1fr) 74px auto;
    }
    .identity-label {
        color: #334155;
        font-size: 15px;
        font-weight: 900;
        white-space: nowrap;
    }
    .identity-value {
        color: #0f172a;
        font-size: clamp(19px, 2.2vw, 27px);
        font-weight: 950;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .identity-ticker {
        color: #0f172a;
        font-size: clamp(22px, 2.5vw, 30px);
        font-weight: 950;
        line-height: 1.1;
    }
    .class-label {
        color: #475569;
        font-size: 14px;
        font-weight: 900;
        white-space: nowrap;
        text-align: left;
    }
    .class-pill {
        justify-self: start;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #f3e8ff;
        color: #7c3aed;
        border: 1px solid #e9d5ff;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 13px;
        font-weight: 900;
        white-space: nowrap;
    }

    .search-help {
        color: #475569;
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .search-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 160px;
        gap: 10px;
        align-items: end;
        margin-bottom: 10px;
    }
    .search-grid [data-testid="stTextInput"] label {
        display: none !important;
    }
    .search-grid [data-testid="stTextInput"] input {
        height: 42px !important;
        min-height: 42px !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 14px !important;
    }
    .search-grid .stButton > button,
    .search-action-row .stButton > button {
        border-radius: 10px !important;
        font-weight: 900 !important;
    }
    .search-action-row .stButton > button {
        height: 42px !important;
        background: linear-gradient(135deg, #08224f 0%, #0b3a86 100%) !important;
        color: white !important;
        border: none !important;
        box-shadow: 0 7px 16px rgba(8,34,79,.18);
    }

    .section-title {
        color: #0f172a;
        font-size: 17px;
        font-weight: 950;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .section-text {
        color: #334155;
        font-size: 14px;
        line-height: 1.65;
        font-weight: 650;
    }
    .section-class-grid {
        color: #334155;
        font-size: 14px;
        line-height: 1.7;
        font-weight: 750;
    }

    .metric-card {
        min-height: 76px !important;
        padding: 10px 12px !important;
        border-radius: 12px !important;
        margin-bottom: 10px !important;
        border: 1px solid #e4eaf1 !important;
        box-shadow: none !important;
    }
    .metric-label2 {
        font-size: 12px !important;
        margin-bottom: 4px !important;
        color: #475569 !important;
    }
    .metric-value2 {
        font-size: clamp(17px, 1.7vw, 24px) !important;
        color: #0f172a !important;
        font-weight: 900 !important;
        line-height: 1.15 !important;
    }
    .metric-sub {
        font-size: 10.5px !important;
        margin-top: 5px !important;
        color: #64748b !important;
        font-weight: 700 !important;
    }

    .chart-card .stPlotlyChart {
        margin-top: -6px !important;
    }
    .chart-card .js-plotly-plot .plotly .main-svg {
        border-radius: 10px;
    }

    .notice {
        background: #fff9ed;
        border: 1px solid #f5d8a1;
        border-left: 4px solid #f59e0b;
        border-radius: 12px;
        padding: 12px 14px;
        color: #7c4a03;
        font-size: 13px;
        line-height: 1.6;
        margin-bottom: 14px;
    }
    .safe {
        background: #ecfdf3;
        border: 1px solid #bbf7d0;
        border-left: 4px solid #22c55e;
        border-radius: 12px;
        padding: 12px 14px;
        color: #166534;
        font-size: 13px;
        line-height: 1.6;
        margin-bottom: 14px;
    }

    @media (max-width: 900px) {
        .hero-title-main {
            white-space: normal;
        }
        .identity-row.company,
        .identity-row.ticker {
            grid-template-columns: 1fr !important;
        }
        .class-label {
            margin-top: -2px;
        }
        .search-grid {
            grid-template-columns: 1fr !important;
        }
    }

    /* AI_STOCK_V25_STREAMLIT_SAFE_UI_CSS */
    .block-container {
        max-width: 1220px !important;
        padding-top: 1.85rem !important;
        padding-left: 1.35rem !important;
        padding-right: 1.35rem !important;
    }

    .v25-card {
        background: #ffffff;
        border: 1px solid #dbe4ef;
        border-radius: 16px;
        box-shadow: 0 5px 16px rgba(15,23,42,.05);
        padding: 14px 16px;
        margin-bottom: 14px;
    }
    .v25-card-title {
        color: #0f172a;
        font-size: 17px;
        font-weight: 950;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .v25-identity-table {
        border: 1px solid #e4e9f0;
        border-radius: 12px;
        overflow: hidden;
        background: #fcfdff;
    }
    .v25-row {
        display: grid;
        gap: 12px;
        padding: 14px 16px;
        align-items: center;
    }
    .v25-row + .v25-row {
        border-top: 1px solid #e9eef5;
    }
    .v25-company-row {
        grid-template-columns: 160px minmax(0, 1fr);
    }
    .v25-ticker-row {
        grid-template-columns: 160px minmax(0, 1fr) 74px auto;
    }
    .v25-label {
        color: #334155;
        font-size: 15px;
        font-weight: 900;
        white-space: nowrap;
    }
    .v25-company-value {
        color: #0f172a;
        font-size: clamp(19px, 2.2vw, 27px);
        font-weight: 950;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .v25-ticker-value {
        color: #0f172a;
        font-size: clamp(22px, 2.5vw, 30px);
        font-weight: 950;
        line-height: 1.1;
    }
    .v25-class-pill {
        justify-self: start;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #f3e8ff;
        color: #7c3aed;
        border: 1px solid #e9d5ff;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 13px;
        font-weight: 900;
        white-space: nowrap;
    }
    .v25-section-text {
        color: #334155;
        font-size: 14px;
        line-height: 1.65;
        font-weight: 650;
    }
    .v25-search-note {
        color: #475569;
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .v25-search-box {
        background: #ffffff;
        border: 1px solid #dbe4ef;
        border-radius: 16px;
        box-shadow: 0 5px 16px rgba(15,23,42,.05);
        padding: 14px 16px;
        margin-bottom: 14px;
    }
    .v25-search-box [data-testid="stTextInput"] label {
        display: none !important;
    }
    .v25-search-box [data-testid="stTextInput"] input {
        height: 42px !important;
        min-height: 42px !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 14px !important;
    }
    .v25-search-box .stButton > button {
        height: 42px !important;
        border-radius: 10px !important;
        font-weight: 900 !important;
    }
    .v25-search-box .v25-search-button .stButton > button {
        background: linear-gradient(135deg, #08224f 0%, #0b3a86 100%) !important;
        color: white !important;
        border: none !important;
    }
    .v25-section-card {
        background: #ffffff;
        border: 1px solid #dbe4ef;
        border-radius: 16px;
        box-shadow: 0 5px 16px rgba(15,23,42,.05);
        padding: 14px 16px;
        margin-bottom: 14px;
    }
    .v25-section-title {
        color: #0f172a;
        font-size: 17px;
        font-weight: 950;
        margin-bottom: 8px;
    }

    @media (max-width: 900px) {
        .v25-company-row, .v25-ticker-row {
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

    # 画面更新/F5後も、Googleスプレッドシートに保存済みの銘柄をAI関連図へ復元する
    try:
        persistent_df = get_persistent_favorites_df()
        for _, prow in persistent_df.iterrows():
            cat = str(prow.get("category", "未分類") or "未分類")
            ticker = str(prow.get("ticker", "")).upper().strip()
            company = str(prow.get("company", "")).strip()
            if not ticker:
                continue
            fav_names[ticker] = company
            if cat not in category_map:
                category_map[cat] = []
            if ticker not in category_map[cat]:
                category_map[cat].append(ticker)
    except Exception:
        pass

    # セッション内のお気に入りも追加
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
            all_map_df = get_all_registered_df()
            hit = all_map_df[(all_map_df["ticker"] == t) | (all_map_df["yf_ticker"] == t)]
            if not hit.empty:
                name = hit.iloc[0]["company"]
                display = hit.iloc[0]["ticker"]
            else:
                name = fav_names.get(t, "")
                display = t

            active = " active" if selected in [display.upper(), t.upper()] else ""
            safe_display = str(display).replace('"', '&quot;')
            safe_name = str(name).replace('"', '&quot;')
            items.append(
                '<div class="stock-node{}" onclick="openTicker(\'{}\')" title="{}を開く">'
                '<div class="ticker">{}</div>'
                '<div class="company">{}</div>'
                '</div>'.format(active, safe_display, safe_display, safe_display, safe_name)
            )

        block = (
            '<div class="category-card">'
            '<div class="category-title">{}</div>'
            '<div class="stock-list">{}</div>'
            '</div>'
        ).format(cat, "".join(items))
        blocks.append(block)

    # CSSの { } は .format で壊れないように、HTML全体は通常文字列で組み立てる
    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #f8fafc;
        margin: 0;
        padding: 12px;
        overflow-x: hidden;
        color: #0f172a;
    }
    .map-wrap {
        width: 100%;
        box-sizing: border-box;
        background: #ffffff;
        border: 1px solid #dbe4ef;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 5px 16px rgba(15,23,42,.05);
    }
    .ai-head {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 18px;
        padding-bottom: 14px;
        border-bottom: 1px solid #e5e7eb;
    }
    .ai-logo {
        width: 64px;
        height: 64px;
        border-radius: 18px;
        background: linear-gradient(135deg, #08224f, #1d4ed8);
        color: white;
        font-size: 30px;
        font-weight: 950;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 10px 22px rgba(15,23,42,.18);
    }
    .ai-title {
        font-size: 26px;
        font-weight: 950;
        color: #0f172a;
        line-height: 1.15;
    }
    .ai-sub {
        font-size: 13px;
        font-weight: 700;
        color: #64748b;
        margin-top: 4px;
    }
    .grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
    }
    .category-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 12px;
        box-shadow: 0 3px 10px rgba(15,23,42,.035);
        min-width: 0;
    }
    .category-title {
        font-size: 17px;
        font-weight: 950;
        color: #0f172a;
        margin-bottom: 10px;
        padding-bottom: 7px;
        border-bottom: 3px solid #60a5fa;
        display: inline-block;
    }
    .stock-list {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }
    .stock-node {
        border: 1px solid #dbe4ef;
        background: #f8fafc;
        border-radius: 12px;
        padding: 9px 10px;
        min-width: 0;
        display: block;
        text-decoration: none;
        color: inherit;
        cursor: pointer;
        user-select: none;
    }
    .stock-node:hover {
        border-color: #2563eb;
        background: #eff6ff;
        transform: translateY(-1px);
    }
    .stock-node.active {
        border: 2px solid #f59e0b;
        background: #fff7ed;
    }
    .ticker {
        font-size: 15px;
        font-weight: 950;
        color: #0f172a;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .company {
        font-size: 11px;
        font-weight: 700;
        color: #64748b;
        margin-top: 3px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    @media (max-width: 900px) {
        .grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    @media (max-width: 620px) {
        .grid {
            grid-template-columns: 1fr;
        }
        .stock-list {
            grid-template-columns: 1fr;
        }
    }
    </style>

    <script>
    function openTicker(ticker) {
        const t = encodeURIComponent(String(ticker || "").trim().toUpperCase());
        if (!t) return;

        // iframe内にStreamlitアプリを読み込ませない。
        // 親ページのURLだけを書き換えて、親側のStreamlitに読み取らせる。
        const newHash = "#open_ticker=" + t + "&from=ai";

        try {
            if (window.parent && window.parent !== window) {
                window.parent.location.hash = newHash;
                window.parent.postMessage({type: "open_ticker", ticker: t, from: "ai"}, "*");
                return;
            }
        } catch (e) {}

        try {
            window.top.location.hash = newHash;
            window.top.postMessage({type: "open_ticker", ticker: t, from: "ai"}, "*");
            return;
        } catch (e) {}

        window.location.hash = newHash;
    }
    </script>
    </head>
    <body>
        <div class="map-wrap">
            <div class="ai-head">
                <div class="ai-logo">AI</div>
                <div>
                    <div class="ai-title">AI関連図</div>
                    <div class="ai-sub">AIに必要な部品・素材・電力・通信・データセンターを分類表示</div>
                </div>
            </div>
            <div class="grid">
                __BLOCKS__
            </div>
        </div>
    </body>
    </html>
    """
    return html.replace("__BLOCKS__", "".join(blocks))

period_map = {"1ヶ月": "1mo", "3ヶ月": "3mo", "6ヶ月": "6mo", "1年": "1y", "5年": "5y"}

def show_external_links(row):
    st.subheader("🔎 外部調査リンク")
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
        ("EPS", "eps"), ("ROE", "roe"), ("決算日", "earnings_date"), ("ニュース見出し", "news_headline"),
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
        add_registered_extra_stock(row, final_cat)
        saved, msg = save_stock_to_google_sheet(row, final_cat)
        if saved:
            st.success(f'{row["ticker"]} を「{final_cat}」に永久保存しました。AI関連図と登録銘柄一覧で確認できます。')
        else:
            st.warning(f'{row["ticker"]} を一時登録しました。永久保存は未完了：{msg if msg else "原因不明。API設定確認の接続エラーを見てください。"}')

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

    top_left, top_right = st.columns([1.22, 1.0], gap="large")

    with top_left:
        st.markdown(
            f"""
            <div class="v25-card">
                <div class="v25-card-title">🏢 企業情報</div>
                <div class="v25-identity-table">
                    <div class="v25-row v25-company-row">
                        <div class="v25-label">会社名</div>
                        <div class="v25-company-value">{display_company_name}</div>
                    </div>
                    <div class="v25-row v25-ticker-row">
                        <div class="v25-label">ティッカーコード</div>
                        <div class="v25-ticker-value">{row["ticker"]}</div>
                        <div class="v25-label">分類</div>
                        <div class="v25-class-pill">{display_category or "未取得"}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_right:
        # HTMLの中にStreamlit部品を入れない。カードはStreamlitコンテナとして安全に作る。
        with st.container():
            st.markdown('<div class="v25-search-box">', unsafe_allow_html=True)
            st.markdown('<div class="v25-card-title">🔎 ティッカーコード検索</div>', unsafe_allow_html=True)
            input_col, fav_col = st.columns([1.25, 0.8], gap="small")
            with input_col:
                st.text_input(
                    "ティッカーコード検索",
                    key="ticker_search_input",
                    on_change=sync_ticker_input,
                    placeholder="例：AAPL",
                    label_visibility="collapsed",
                )
            with fav_col:
                fav_clicked = st.button("☆ お気に入り登録", key=f"fav_top_{row['ticker']}", use_container_width=True)

            st.markdown('<div class="v25-search-button">', unsafe_allow_html=True)
            search_clicked = st.button("🔍　検索", key=f"search_btn_{row['ticker']}", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    if fav_clicked:
        add_favorite_stock(row["ticker"], display_company_name, display_category)
        add_registered_extra_stock(row, display_category)
        saved, msg = save_stock_to_google_sheet(row, display_category)
        if saved:
            st.success(f'{row["ticker"]} を「{display_category}」に永久保存しました。{msg}')
        else:
            st.warning(f'{row["ticker"]} を一時登録しました。永久保存は未完了：{msg if msg else "原因不明。API設定確認の接続エラーを見てください。"}')

    if search_clicked:
        sync_ticker_input()
        st.rerun()

    st.markdown(
        f"""
        <div class="v25-section-card">
            <div class="v25-section-title">📘 何を作るか / 事業内容</div>
            <div class="v25-section-text">{display_business}</div>
        </div>
        <div class="v25-section-card">
            <div class="v25-section-title">🔗 AIとのつながり</div>
            <div class="v25-section-text">{display_relation}</div>
        </div>
        <div class="v25-section-card">
            <div class="v25-section-title">🏷 分類</div>
            <div class="v25-section-text">
                セクター：{display_category or "未取得"}<br>
                業種：{display_industry or "未取得"}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if bool(row.get("_virtual", False)):
        pass

    st.markdown('<div class="v25-section-card"><div class="v25-section-title">▦ データ自動取得</div>', unsafe_allow_html=True)
    if not FMP_API_KEY and not ALPHAVANTAGE_API_KEY and not FINNHUB_API_KEY:
        pass
    else:
        active = []
        if FMP_API_KEY: active.append("FMP")
        if FINNHUB_API_KEY: active.append("Finnhub")
        if ALPHAVANTAGE_API_KEY: active.append("Alpha Vantage")
        st.markdown(f'<div class="safe">補助APIが有効です：<b>{", ".join(active)}</b></div>', unsafe_allow_html=True)

    dy = None
    if combined["dividend_yield"] is not None:
        try:
            dy = float(combined["dividend_yield"]) * 100 if float(combined["dividend_yield"]) < 1 else float(combined["dividend_yield"])
        except Exception:
            dy = combined["dividend_yield"]

    roe = None
    if combined.get("roe") is not None:
        try:
            roe = float(combined["roe"]) * 100 if abs(float(combined["roe"])) <= 1 else float(combined["roe"])
        except Exception:
            roe = combined["roe"]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: metric_card("株価", fmt_price(combined["price"], combined["currency"]), delta_text(combined["change_pct"]))
    with c2: metric_card("時価総額", fmt_market_cap(combined["market_cap"]), f'取得元：{source_map.get("market_cap")}')
    with c3: metric_card("PER", fmt_num(combined["per"]), f'取得元：{source_map.get("per")}')
    with c4: metric_card("PBR", fmt_num(combined["pbr"]), f'取得元：{source_map.get("pbr")}')
    with c5: metric_card("EPS", fmt_num(combined.get("eps")), f'取得元：{source_map.get("eps", "未取得")}')
    with c6: metric_card("ROE", fmt_percent(roe), f'取得元：{source_map.get("roe", "未取得")}')

    c7, c8, c9 = st.columns(3)
    with c7: metric_card("利回り", fmt_percent(dy), f'取得元：{source_map.get("dividend_yield")}')
    with c8: metric_card("決算日", fmt_date_value(combined.get("earnings_date")), f'取得元：{source_map.get("earnings_date", "未取得")}')
    with c9: metric_card("ニュース見出し", fmt_news_title(combined.get("news_headline")), f'取得元：{source_map.get("news_headline", "未取得")}')

    with st.expander("📌 取得元を確認する"):
        show_source_table(source_map)

    st.caption("※ 自動取得データは参考値です。無料API / yfinance は欠損・遅延・制限があります。投資判断は自己責任でお願いします。")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="v25-section-card"><div class="v25-section-title">📈 株価チャート</div>', unsafe_allow_html=True)
    hist = get_yf_history(row["yf_ticker"], period_map[period_label])
    if hist.empty:
        st.warning("チャートデータを取得できませんでした。")
    else:
        date_col = "Date" if "Date" in hist.columns else hist.columns[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist[date_col], y=hist["Close"], mode="lines", name="Close"))
        fig.update_layout(
            height=340,
            margin=dict(l=18, r=18, t=20, b=18),
            hovermode="x unified",
            plot_bgcolor="#ffffff",
            paper_bgcolor="#ffffff",
        )
        st.plotly_chart(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    show_external_links(row)
    show_register_box(row)
# -----------------------------
# UI
# -----------------------------
st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
st.markdown(
    '''
    <div class="app-hero">
        <div class="hero-icon">📖</div>
        <div class="hero-title-wrap">
            <div class="hero-title-main">AI関連株コード辞典 v44</div>
            <div class="hero-sub-main">会社情報・AIとのつながり・分類を見やすく整理するリサーチ画面</div>
        </div>
    </div>
    ''',
    unsafe_allow_html=True,
)


st.markdown("""
<script>
(function() {
  function syncHashToQuery() {
    try {
      const hash = window.location.hash || "";
      if (!hash.startsWith("#open_ticker=")) return;
      const params = new URLSearchParams(hash.slice(1));
      const t = params.get("open_ticker");
      const src = params.get("from") || "ai";
      if (!t) return;
      const url = new URL(window.location.href);
      url.hash = "";
      url.searchParams.set("open_ticker", t);
      url.searchParams.set("from", src);
      window.location.replace(url.toString());
    } catch(e) {}
  }
  syncHashToQuery();
  window.addEventListener("hashchange", syncHashToQuery);
  window.addEventListener("message", function(ev) {
    try {
      if (!ev.data || ev.data.type !== "open_ticker") return;
      const t = ev.data.ticker;
      const src = ev.data.from || "ai";
      if (!t) return;
      const url = new URL(window.location.href);
      url.hash = "";
      url.searchParams.set("open_ticker", t);
      url.searchParams.set("from", src);
      window.location.replace(url.toString());
    } catch(e) {}
  });
})();
</script>
""", unsafe_allow_html=True)

apply_query_open_ticker()

st.sidebar.markdown(
    """
    <div class="sidebar-brand">
        <div class="sidebar-brand-top">
            <div class="sidebar-logo">📖</div>
            <div class="sidebar-brand-title">AI関連株コード辞典<br>v44</div>
        </div>
        <div class="sidebar-brand-sub">
            AIと企業のつながりを見やすく整理するリサーチ画面
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown('<div class="sidebar-menu-label">表示モード</div>', unsafe_allow_html=True)
MODE_OPTIONS = ["ティッカー検索", "キーワード検索", "カテゴリ表示", "AI関連図", "全銘柄一覧", "API設定確認"]

if "display_mode" not in st.session_state:
    st.session_state.display_mode = "ティッカー検索"

# 外部ボタンから表示モードを変えられるように、radioのkeyは別名にする
try:
    default_mode_index = MODE_OPTIONS.index(st.session_state.display_mode)
except Exception:
    default_mode_index = 0

mode = st.sidebar.radio(
    "表示モード",
    MODE_OPTIONS,
    index=default_mode_index,
    key="display_mode_radio",
)

st.session_state.display_mode = mode


st.sidebar.markdown('<div class="sidebar-menu-label">チャート期間</div>', unsafe_allow_html=True)
period_label = st.sidebar.selectbox("チャート期間", ["1ヶ月", "3ヶ月", "6ヶ月", "1年", "5年"], index=2)

st.sidebar.markdown(
    """
    <div class="sidebar-note">
        <b>データについて</b><br>
        本データは公開情報をもとに収集・整理したものです。<br>
        投資助言を目的としたものではありません。<br><br>
        米国株例：NVDA / AAPL / MSFT / D / T<br>
        日本株例：7203.T / 9984.T / 6857.T
    </div>
    """,
    unsafe_allow_html=True,
)

if mode == "ティッカー検索":

    if st.session_state.get("return_to_mode"):
        back_label = "← 全銘柄一覧へ戻る" if st.session_state.return_to_mode == "全銘柄一覧" else "← AI関連図へ戻る"
        if st.button(back_label, use_container_width=True):
            return_to_previous_mode()
    ticker = st.session_state.get("last_ticker", "NVDA").strip().upper()
    row = build_row_from_ticker(ticker)
    show_stock_page(row)

elif mode == "キーワード検索":
    keyword = st.text_input("キーワードを入力", value="冷却").strip()
    if keyword:
        all_df = get_all_registered_df()
        mask = (
            all_df["ticker"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["yf_ticker"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["company"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["category"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["business"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["ai_relation"].astype(str).str.contains(keyword, case=False, na=False)
            | all_df["keywords"].astype(str).str.contains(keyword, case=False, na=False)
        )
        result = all_df[mask]
        st.subheader(f"検索結果：{keyword}")
        if result.empty:
            st.warning("該当する登録済み銘柄がありません。")
        else:
            st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

elif mode == "カテゴリ表示":
    all_df = get_all_registered_df()
    category = st.selectbox("カテゴリを選択", sorted(all_df["category"].dropna().unique().tolist()))
    result = all_df[all_df["category"] == category]
    st.subheader(f"カテゴリ：{category}")
    st.dataframe(result[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]], use_container_width=True, hide_index=True)

elif mode == "AI関連図":
    st.subheader("🗺 AI関連図")
    st.caption("関連図内のティッカーコードを押すと、ティッカー検索ページで会社情報を表示します。")
    components.html(make_mindmap_html(), height=980, scrolling=False)

    fav_df = get_persistent_favorites_df()
    st.subheader("⭐ 保存済み・一時登録銘柄")
    if fav_df.empty:
        st.info("まだ登録された銘柄はありません。ティッカー検索から登録できます。")
    else:
        view_df = fav_df[["ticker", "company", "category", "business", "ai_score"]].copy()
        view_df["category"] = view_df["category"].apply(normalize_display_category)
        st.dataframe(view_df, use_container_width=True, hide_index=True)

        with st.expander("登録解除"):
            target = st.selectbox("解除する銘柄", fav_df["ticker"].tolist())
            if st.button("選択した銘柄を解除", use_container_width=True):
                remove_favorite_stock(target)
                remove_registered_extra_stock(target)
                ok, msg = delete_stock_from_google_sheet(target)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
                st.rerun()

elif mode == "全銘柄一覧":
    st.subheader("登録銘柄一覧")
    st.caption("各行の「開く」を押すと、ティッカー検索ページへ移動してその銘柄の会社情報を表示します。")

    all_df = get_all_registered_df()
    list_df = all_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score", "official_ir_url"]].copy()
    list_df["category"] = list_df["category"].apply(normalize_display_category)
    list_df = list_df.drop_duplicates(subset=["ticker"], keep="last").reset_index(drop=True)

    # コンパクトな枠付き一覧用CSS
    st.markdown("""
    <style>
    .compact-stock-row {
        border: 1px solid #dbe4ef;
        border-radius: 10px;
        background: #ffffff;
        padding: 7px 9px;
        margin: 4px 0;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }
    .compact-stock-row .tkr {
        font-size: 15px;
        font-weight: 900;
        color: #0f172a;
        line-height: 1.1;
    }
    .compact-stock-row .sub {
        font-size: 11px;
        color: #64748b;
        line-height: 1.15;
        margin-top: 1px;
    }
    .compact-stock-row .company {
        font-size: 13px;
        font-weight: 700;
        color: #1f2937;
        line-height: 1.25;
    }
    .compact-stock-row .cat {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: #eef2ff;
        color: #3730a3;
        font-size: 11px;
        font-weight: 800;
        white-space: nowrap;
    }
    .compact-stock-row .biz {
        font-size: 12px;
        color: #334155;
        line-height: 1.25;
    }
    .compact-header {
        font-size: 12px;
        font-weight: 800;
        color: #475569;
        padding: 0 6px 4px 6px;
    }
    </style>
    """, unsafe_allow_html=True)

    if list_df.empty:
        st.info("登録銘柄がありません。")
    else:
        hc = st.columns([0.9, 1.0, 1.5, 1.0, 2.8, 0.75, 0.75])
        for col, name in zip(hc, ["Ticker", "Yahoo", "会社名", "カテゴリ", "事業内容", "AI", ""]):
            col.markdown(f'<div class="compact-header">{name}</div>', unsafe_allow_html=True)

        for i, (_, r) in enumerate(list_df.iterrows()):
            t = str(r["ticker"]).upper()
            yf = str(r.get("yf_ticker", "")).upper()
            company = str(r.get("company", ""))
            cat = str(r.get("category", "未分類"))
            business = str(r.get("business", ""))
            score = str(r.get("ai_score", ""))

            row_cols = st.columns([0.9, 1.0, 1.5, 1.0, 2.8, 0.75, 0.75])
            row_cols[0].markdown(f'<div class="compact-stock-row"><div class="tkr">{t}</div></div>', unsafe_allow_html=True)
            row_cols[1].markdown(f'<div class="compact-stock-row"><div class="sub">{yf}</div></div>', unsafe_allow_html=True)
            row_cols[2].markdown(f'<div class="compact-stock-row"><div class="company">{company}</div></div>', unsafe_allow_html=True)
            row_cols[3].markdown(f'<div class="compact-stock-row"><span class="cat">{cat}</span></div>', unsafe_allow_html=True)
            short_biz = business[:70] + ("…" if len(business) > 70 else "")
            row_cols[4].markdown(f'<div class="compact-stock-row"><div class="biz">{short_biz}</div></div>', unsafe_allow_html=True)
            row_cols[5].markdown(f'<div class="compact-stock-row"><div class="tkr">{score}</div></div>', unsafe_allow_html=True)
            with row_cols[6]:
                if st.button("開く", key=f"open_row_{t}_{i}", use_container_width=True):
                    open_ticker_from_button(t, return_to="全銘柄一覧")

    google_df = load_google_sheet_stocks()
    if google_sheet_enabled():
        st.success(f"Googleスプレッドシート保存：有効 / 保存済み {len(google_df)} 銘柄")
    else:
        st.warning("Googleスプレッドシート保存：未設定です。Secretsを設定すると永久保存できます。")

    with st.expander("Googleスプレッドシート保存済みの管理"):
        if google_df.empty:
            st.info("Googleスプレッドシートに保存済みの銘柄はありません。")
        else:
            gview = google_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]].copy()
            gview["category"] = gview["category"].apply(normalize_display_category)
            st.dataframe(gview, use_container_width=True, hide_index=True)

            target_g = st.selectbox("Google保存から削除する銘柄", google_df["ticker"].tolist())
            if st.button("選択した銘柄をGoogle保存から削除", use_container_width=True):
                ok, msg = delete_stock_from_google_sheet(target_g)
                if ok:
                    remove_favorite_stock(target_g)
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    extra_df = get_registered_extra_df()
    with st.expander("今回の一時登録とCSV追記用データ"):
        if extra_df.empty:
            st.info("今回の一時登録銘柄はありません。")
        else:
            eview = extra_df[["ticker", "yf_ticker", "company", "category", "business", "ai_score"]].copy()
            eview["category"] = eview["category"].apply(normalize_display_category)
            st.dataframe(eview, use_container_width=True, hide_index=True)

            target = st.selectbox("一時登録を解除する銘柄", extra_df["ticker"].tolist())
            if st.button("選択した一時登録を解除", use_container_width=True):
                remove_registered_extra_stock(target)
                remove_favorite_stock(target)
                st.success(f"{target} を一時登録から解除しました。")
                st.rerun()

            st.markdown("### 📋 stocks.csvへ追記するCSV")
            csv_lines = "\n".join([build_csv_line_from_row(r) for _, r in extra_df.iterrows()])
            st.code(csv_lines, language="csv")

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
    st.subheader("Googleスプレッドシート永久保存")
    st.write("GOOGLE_SHEET_ID:", "設定済み" if get_google_sheet_id() else "未設定")
    st.write("gcp_service_account:", "設定済み" if get_service_account_info() else "未設定")
    st.write("gspread:", "使用可能" if gspread is not None else "未インストール")
    st.write("接続エラー:", st.session_state.get("google_sheet_last_error", "") or "なし")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("接続キャッシュをクリア", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.session_state.google_sheet_last_error = ""
            st.success("キャッシュをクリアしました。再度Google保存テストを押してください。")
    with c2:
        if st.button("Google接続だけ確認", use_container_width=True):
            ws = get_gspread_worksheet()
            if ws is not None:
                st.success("Googleスプレッドシート接続OK：stocksシートを確認できました。")
            else:
                st.error("Google接続NG：" + (st.session_state.get("google_sheet_last_error", "") or "原因不明"))


    if st.button("Google保存テスト", use_container_width=True):
        test_row = {
            "ticker": "TEST",
            "yf_ticker": "TEST",
            "company": "接続テスト",
            "category": "テスト",
            "business": "Googleスプレッドシート保存テスト",
            "ai_relation": "テスト",
            "ai_score": 1,
            "keywords": "test",
            "related": "",
            "official_ir_url": "",
        }
        ok, msg = save_stock_to_google_sheet(test_row, "テスト")
        if ok:
            st.success("Google保存テスト成功：" + msg)
        else:
            st.error("Google保存テスト失敗：" + msg)


    st.markdown(
        """
        ### Googleスプレッドシート保存を有効にするSecrets例

        ```toml
        GOOGLE_SHEET_ID = "GoogleスプレッドシートID"

        [gcp_service_account]
        type = "service_account"
        project_id = "..."
        private_key_id = "..."
        private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
        client_email = "..."
        client_id = "..."
        auth_uri = "https://accounts.google.com/o/oauth2/auth"
        token_uri = "https://oauth2.googleapis.com/token"
        auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
        client_x509_cert_url = "..."
        ```

        Googleスプレッドシート側では、サービスアカウントの `client_email` に編集権限を付けてください。
        シート名は `stocks` を使います。無ければ自動作成します。
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
