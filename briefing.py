#!/usr/bin/env python3
"""
Briefing diario para traders de XAU/USD - v2
Añade: niveles técnicos (pivots, ATR), rango sesión asiática,
yield real US10Y (TIPS), y resumen del cierre de NY.
"""

import os
import json
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import yfinance as yf
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MADRID_TZ = ZoneInfo("Europe/Madrid")
GOLD_TICKER = "GC=F"


# ---------- Calendario económico ----------

def get_economic_calendar():
    """Eventos USD de alta importancia para hoy desde ForexFactory."""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        events = response.json()
        today = datetime.now(MADRID_TZ).date()

        relevant = []
        for event in events:
            try:
                event_dt = datetime.fromisoformat(event["date"]).astimezone(MADRID_TZ)
                if (event_dt.date() == today
                        and event.get("country") == "USD"
                        and event.get("impact") == "High"):
                    relevant.append({
                        "time": event_dt.strftime("%H:%M"),
                        "title": event["title"],
                        "forecast": event.get("forecast", "") or "—",
                        "previous": event.get("previous", "") or "—",
                    })
            except (KeyError, ValueError):
                continue
        return sorted(relevant, key=lambda x: x["time"])
    except Exception as e:
        return [{"error": f"No se pudo cargar calendario: {e}"}]


# ---------- Datos de mercado ----------

def get_market_data():
    """Precio actual y rango semanal de XAU/USD, DXY y US10Y."""
    tickers = {
        "XAU/USD": GOLD_TICKER,
        "DXY":     "DX-Y.NYB",
        "US10Y":   "^TNX",
    }
    data = {}
    for name, ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if not hist.empty and len(hist) >= 2:
                current = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                week_high = float(hist["High"].max())
                week_low = float(hist["Low"].min())
                change_pct = ((current - prev) / prev) * 100
                data[name] = {
                    "price": round(current, 2),
                    "change_pct": round(change_pct, 2),
                    "week_high": round(week_high, 2),
                    "week_low": round(week_low, 2),
                }
        except Exception as e:
            data[name] = {"error": str(e)}
    return data


# ---------- Análisis técnico ----------

def get_technical_levels(ticker_str=GOLD_TICKER):
    """Pivot points clásicos y ATR(14) basados en datos diarios."""
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="30d")
        if hist.empty or len(hist) < 15:
            return None

        # Pivots basados en el último día completo
        last = hist.iloc[-1]
        H, L, C = float(last["High"]), float(last["Low"]), float(last["Close"])
        PP = (H + L + C) / 3
        R1 = 2 * PP - L
        S1 = 2 * PP - H
        R2 = PP + (H - L)
        S2 = PP - (H - L)
        R3 = H + 2 * (PP - L)
        S3 = L - 2 * (H - PP)

        # ATR(14)
        h = hist.copy()
        h["H-L"] = h["High"] - h["Low"]
        h["H-PC"] = (h["High"] - h["Close"].shift(1)).abs()
        h["L-PC"] = (h["Low"] - h["Close"].shift(1)).abs()
        h["TR"] = h[["H-L", "H-PC", "L-PC"]].max(axis=1)
        atr = float(h["TR"].tail(14).mean())

        return {
            "PP": round(PP, 2),
            "R1": round(R1, 2), "R2": round(R2, 2), "R3": round(R3, 2),
            "S1": round(S1, 2), "S2": round(S2, 2), "S3": round(S3, 2),
            "ATR14": round(atr, 2),
        }
    except Exception:
        return None


def get_asian_session_range(ticker_str=GOLD_TICKER):
    """Rango de la sesión asiática actual o más reciente (00:00-08:00 UTC)."""
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="2d", interval="1h")
        if hist.empty:
            return None

        if hist.index.tz is None:
            hist.index = hist.index.tz_localize("UTC")
        else:
            hist.index = hist.index.tz_convert("UTC")

        today_utc = datetime.now(timezone.utc).date()
        asian_start = datetime.combine(today_utc, datetime.min.time(), tzinfo=timezone.utc)
        asian_end = asian_start + timedelta(hours=8)

        asian_data = hist[(hist.index >= asian_start) & (hist.index < asian_end)]
        if asian_data.empty:
            return None

        return {
            "high": round(float(asian_data["High"].max()), 2),
            "low": round(float(asian_data["Low"].min()), 2),
            "range_pts": round(float(asian_data["High"].max() - asian_data["Low"].min()), 2),
        }
    except Exception:
        return None


# ---------- Yield real (TIPS) desde FRED ----------

def get_real_yield():
    """10Y TIPS yield (yield real). Driver fundamental más limpio del oro."""
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
        response = requests.get(url, timeout=15)
        lines = response.text.strip().split("\n")

        latest_val, latest_date, prev_val = None, None, None
        for line in reversed(lines[1:]):
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() not in ("", "."):
                if latest_val is None:
                    latest_val = float(parts[1])
                    latest_date = parts[0]
                else:
                    prev_val = float(parts[1])
                    break

        if latest_val is None:
            return None

        change_bp = round((latest_val - prev_val) * 100, 1) if prev_val else 0.0
        return {
            "value": round(latest_val, 3),
            "change_bp": change_bp,
            "date": latest_date,
        }
    except Exception:
        return None


# ---------- Cierre sesión NY ----------

def get_ny_session_summary(ticker_str=GOLD_TICKER):
    """Resumen de la última sesión NY del oro (13:00-22:00 UTC)."""
    try:
        t = yf.Ticker(ticker_str)
        hist = t.history(period="3d", interval="1h")
        if hist.empty:
            return None

        if hist.index.tz is None:
            hist.index = hist.index.tz_localize("UTC")
        else:
            hist.index = hist.index.tz_convert("UTC")

        today_utc = datetime.now(timezone.utc).date()
        for days_back in [1, 2, 3]:
            day = today_utc - timedelta(days=days_back)
            ny_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13)
            ny_end = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=22)
            ny_data = hist[(hist.index >= ny_start) & (hist.index <= ny_end)]
            if not ny_data.empty:
                open_p = float(ny_data["Open"].iloc[0])
                close_p = float(ny_data["Close"].iloc[-1])
                high = float(ny_data["High"].max())
                low = float(ny_data["Low"].min())
                change_pct = ((close_p - open_p) / open_p) * 100
                return {
                    "date": day.strftime("%d/%m"),
                    "open": round(open_p, 2),
                    "close": round(close_p, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "range_pts": round(high - low, 2),
                    "change_pct": round(change_pct, 2),
                }
        return None
    except Exception:
        return None


# ---------- Noticias ----------

def get_news():
    """Noticias geopolíticas y de oro de las últimas 24h vía RSS."""
    feeds = {
        "Al Jazeera":     "https://www.aljazeera.com/xml/rss/all.xml",
        "BBC World":      "http://feeds.bbci.co.uk/news/world/rss.xml",
        "Kitco Gold":     "https://www.kitco.com/rss/KitcoNews.xml",
        "Reuters Mkts":   "https://www.investing.com/rss/news_25.rss",
        "Investing Gold": "https://www.investing.com/rss/commodities_Gold.rss",
    }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    all_news = []

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                if pub_date and pub_date < cutoff:
                    continue

                all_news.append({
                    "source": source,
                    "title": entry.title,
                    "summary": entry.get("summary", "")[:300],
                })
        except Exception:
            continue
    return all_news


# ---------- Síntesis con IA (opcional) ----------

def synthesize_with_claude(market_data, calendar, news, technical, asian, real_yield, ny):
    if not ANTHROPIC_API_KEY:
        return None

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Eres un analista experto en XAU/USD. Crea un briefing matutino para un trader.

DATOS DE MERCADO:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

NIVELES TÉCNICOS XAU/USD (pivots clásicos + ATR):
{json.dumps(technical, indent=2, ensure_ascii=False)}

RANGO SESIÓN ASIÁTICA:
{json.dumps(asian, indent=2, ensure_ascii=False)}

YIELD REAL US10Y (TIPS - driver más relevante para el oro):
{json.dumps(real_yield, indent=2, ensure_ascii=False)}

CIERRE SESIÓN NY DE AYER:
{json.dumps(ny, indent=2, ensure_ascii=False)}

EVENTOS USD HOY (alta importancia, hora Madrid):
{json.dumps(calendar, indent=2, ensure_ascii=False)}

NOTICIAS 24H:
{json.dumps(news[:25], indent=2, ensure_ascii=False)}

INSTRUCCIONES:
1. Resumen ejecutivo (2-3 líneas) con sesgo del día
2. Cierre NY de ayer + rango asiático: ¿qué nos dice del momentum?
3. Yield real: si subió bajista oro, si bajó alcista. Comenta.
4. DXY y US10Y nominal: estado y correlación esperada
5. Eventos del día: cuáles importan al oro y por qué
6. 3-5 noticias más relevantes para el oro
7. Niveles a vigilar: usa pivots, máx/mín asiático y ATR para sugerir zonas
8. Tono profesional, directo. Máximo 700 palabras.
9. Markdown Telegram: *negrita* simple, sin ** ni # ni tablas.
"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        print(f"Error con Claude: {e}")
        return None


# ---------- Formato sin IA ----------

def format_basic_briefing(market_data, calendar, news, technical, asian, real_yield, ny):
    today = datetime.now(MADRID_TZ).strftime("%d/%m/%Y")
    lines = [f"*Briefing XAU/USD — {today}*", ""]

    # Mercado
    lines.append("*Mercado*")
    for name, d in market_data.items():
        if "error" not in d:
            arrow = "🟢" if d["change_pct"] >= 0 else "🔴"
            lines.append(
                f"{arrow} {name}: {d['price']} ({d['change_pct']:+.2f}%) "
                f"| Sem: {d['week_low']}–{d['week_high']}"
            )
    lines.append("")

    # Yield real
    if real_yield:
        sign = "🔴" if real_yield["change_bp"] > 0 else "🟢"
        lines.append("*Yield real US10Y (TIPS)*")
        lines.append(
            f"{sign} {real_yield['value']}% (cambio: {real_yield['change_bp']:+.1f} bp) "
            f"— {real_yield['date']}"
        )
        lines.append("_Sube = bajista oro / Baja = alcista oro_")
        lines.append("")

    # Cierre NY
    if ny:
        arrow = "🟢" if ny["change_pct"] >= 0 else "🔴"
        lines.append(f"*Cierre sesión NY ({ny['date']})*")
        lines.append(
            f"{arrow} Apertura {ny['open']} → Cierre {ny['close']} ({ny['change_pct']:+.2f}%)"
        )
        lines.append(f"Máx {ny['high']} | Mín {ny['low']} | Rango {ny['range_pts']} pts")
        lines.append("")

    # Sesión asiática
    if asian:
        lines.append("*Rango sesión asiática*")
        lines.append(f"Máx {asian['high']} | Mín {asian['low']} | Rango {asian['range_pts']} pts")
        lines.append("_Londres suele romper este rango al abrir_")
        lines.append("")

    # Niveles técnicos
    if technical:
        lines.append("*Niveles técnicos XAU/USD*")
        lines.append(f"Pivot: {technical['PP']}")
        lines.append(f"R: {technical['R1']} / {technical['R2']} / {technical['R3']}")
        lines.append(f"S: {technical['S1']} / {technical['S2']} / {technical['S3']}")
        lines.append(f"ATR(14): {technical['ATR14']} pts (rango medio diario)")
        lines.append("")

    # Calendario
    lines.append("*Eventos clave hoy (USD, alto impacto)*")
    if calendar and "error" not in calendar[0]:
        for ev in calendar:
            lines.append(
                f"• {ev['time']} — {ev['title']} "
                f"(F: {ev['forecast']} / P: {ev['previous']})"
            )
    else:
        lines.append("Sin eventos de alto impacto programados")
    lines.append("")

    # Noticias
    lines.append("*Noticias relevantes (24h)*")
    for item in news[:10]:
        lines.append(f"• [{item['source']}] {item['title']}")

    return "\n".join(lines)


# ---------- Envío ----------

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [message[i:i + 4000] for i in range(0, len(message), 4000)]

    for chunk in chunks:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        if r.status_code != 200:
            requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            })


# ---------- Main ----------

def main():
    print("Generando briefing diario XAU/USD v2...")

    market_data = get_market_data()
    calendar = get_economic_calendar()
    news = get_news()
    technical = get_technical_levels()
    asian = get_asian_session_range()
    real_yield = get_real_yield()
    ny = get_ny_session_summary()

    ai_briefing = synthesize_with_claude(
        market_data, calendar, news, technical, asian, real_yield, ny
    )
    raw_data = format_basic_briefing(
        market_data, calendar, news, technical, asian, real_yield, ny
    )

    if ai_briefing:
        full_message = f"{ai_briefing}\n\n— — —\n\n{raw_data}"
    else:
        full_message = raw_data

    send_telegram(full_message)
    print("Briefing enviado.")


if __name__ == "__main__":
    main()
