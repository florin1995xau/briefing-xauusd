#!/usr/bin/env python3
"""
Briefing diario para traders de XAU/USD.
Envía un resumen de mercado a Telegram cada mañana.
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


# ---------- Recolección de datos ----------

def get_economic_calendar():
    """Eventos USD de alta importancia para hoy desde ForexFactory."""
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        events = response.json()
        today = datetime.now(MADRID_TZ).date()

        relevant = []
        for event in events:
            try:
                event_dt = datetime.fromisoformat(event["date"]).astimezone(MADRID_TZ)
                if (
                    event_dt.date() == today
                    and event.get("country") == "USD"
                    and event.get("impact") == "High"
                ):
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


def get_market_data():
    """Precio actual y rango de XAU/USD, DXY y US10Y."""
    tickers = {
        "XAU/USD": "GC=F",      # Futuros del oro
        "DXY":     "DX-Y.NYB",  # Índice del dólar
        "US10Y":   "^TNX",      # Yield 10 años (en %)
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


# ---------- Síntesis con IA ----------

def synthesize_with_claude(market_data, calendar, news):
    """Usa Claude para crear un briefing en lenguaje natural."""
    if not ANTHROPIC_API_KEY:
        return None

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Eres un analista experto en XAU/USD. Crea un briefing matutino para un trader.

DATOS DE MERCADO ACTUALES:
{json.dumps(market_data, indent=2, ensure_ascii=False)}

EVENTOS ECONÓMICOS USD DE HOY (alta importancia, hora Madrid):
{json.dumps(calendar, indent=2, ensure_ascii=False)}

NOTICIAS DE LAS ÚLTIMAS 24H:
{json.dumps(news[:25], indent=2, ensure_ascii=False)}

INSTRUCCIONES:
1. Resumen ejecutivo de 2-3 líneas: contexto del oro y sesgo del día
2. Eventos del día con su hora y por qué importan al oro (relación con DXY/yields/Fed)
3. Estado de DXY y US10Y y su implicación para XAU/USD (correlación inversa habitual)
4. Selecciona las 3-5 noticias más relevantes para el oro como activo refugio. Ignora ruido.
5. "Niveles a vigilar" basados en máximos/mínimos semanales y números redondos próximos
6. Tono profesional, directo, sin floritura. Máximo 600 palabras.
7. Formato Markdown compatible con Telegram (usa *negrita* con un solo asterisco, NO uses ** dobles, NO uses tablas, NO uses headers con #)
"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        print(f"Error con Claude: {e}")
        return None


# ---------- Formato fallback ----------

def format_basic_briefing(market_data, calendar, news):
    """Briefing básico sin IA por si Claude falla."""
    today = datetime.now(MADRID_TZ).strftime("%d/%m/%Y")
    lines = [f"*Briefing XAU/USD — {today}*", ""]

    lines.append("*Mercado*")
    for name, d in market_data.items():
        if "error" not in d:
            arrow = "🟢" if d["change_pct"] >= 0 else "🔴"
            lines.append(
                f"{arrow} {name}: {d['price']} ({d['change_pct']:+.2f}%) "
                f"| Rango sem: {d['week_low']}–{d['week_high']}"
            )
    lines.append("")

    lines.append("*Eventos clave hoy (USD, alto impacto)*")
    if calendar and "error" not in calendar[0]:
        for ev in calendar:
            lines.append(
                f"• {ev['time']} — {ev['title']} "
                f"(Fcst: {ev['forecast']} / Prev: {ev['previous']})"
            )
    else:
        lines.append("Sin eventos de alto impacto programados")
    lines.append("")

    lines.append("*Noticias relevantes (24h)*")
    for item in news[:10]:
        lines.append(f"• [{item['source']}] {item['title']}")

    return "\n".join(lines)


# ---------- Envío ----------

def send_telegram(message):
    """Envía un mensaje a Telegram, troceando si excede el límite."""
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
            # Reintenta sin markdown si falla por formato
            requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            })


# ---------- Main ----------

def main():
    print("Generando briefing diario XAU/USD...")

    market_data = get_market_data()
    calendar = get_economic_calendar()
    news = get_news()

    # Síntesis con IA, con fallback al formato básico
    ai_briefing = synthesize_with_claude(market_data, calendar, news)

    raw_data = format_basic_briefing(market_data, calendar, news)

    if ai_briefing:
        full_message = f"{ai_briefing}\n\n— — —\n\n{raw_data}"
    else:
        full_message = raw_data

    send_telegram(full_message)
    print("Briefing enviado.")


if __name__ == "__main__":
    main()
