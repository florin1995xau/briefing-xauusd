#!/usr/bin/env python3
"""
Alertas XAU/USD - v2
Dos tipos de alertas:
  - PROXIMIDAD: precio cerca de un pivot (sin importar RSI)
  - SETUP: precio en pivot + RSI extremo (señal accionable)
"""

import os
import json
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ===== CONFIGURACIÓN — edita aquí para ajustar =====
GOLD_TICKER = "GC=F"

# Tolerancias (distancia al nivel en USD)
PROXIMITY_TOLERANCE_PTS = 8.0   # Para alerta de acercamiento
SETUP_TOLERANCE_PTS = 5.0       # Para setup completo

# RSI
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Cooldown - tiempo mínimo entre alertas del mismo tipo/nivel
PROXIMITY_COOLDOWN_HOURS = 1
SETUP_COOLDOWN_HOURS = 2

STATE_FILE = "alert_state.json"
MADRID_TZ = ZoneInfo("Europe/Madrid")
# ====================================================


def calculate_rsi(prices, period=14):
    """RSI de Wilder (igual que TradingView/MT5)."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_price_and_rsi():
    """Precio actual y RSI(14) en M5."""
    try:
        t = yf.Ticker(GOLD_TICKER)
        hist = t.history(period="2d", interval="5m")
        if hist.empty or len(hist) < 20:
            return None, None
        price = float(hist["Close"].iloc[-1])
        rsi = float(calculate_rsi(hist["Close"], 14).iloc[-1])
        return price, rsi
    except Exception as e:
        print(f"Error obteniendo precio/RSI: {e}")
        return None, None


def get_pivots_and_atr():
    """Pivots clásicos del día anterior + ATR(14)."""
    try:
        t = yf.Ticker(GOLD_TICKER)
        hist = t.history(period="30d")
        if hist.empty or len(hist) < 15:
            return None, None

        last = hist.iloc[-1]
        H, L, C = float(last["High"]), float(last["Low"]), float(last["Close"])
        PP = (H + L + C) / 3
        pivots = {
            "PP": round(PP, 2),
            "R1": round(2 * PP - L, 2),
            "R2": round(PP + (H - L), 2),
            "S1": round(2 * PP - H, 2),
            "S2": round(PP - (H - L), 2),
        }

        h = hist.copy()
        h["H-L"] = h["High"] - h["Low"]
        h["H-PC"] = (h["High"] - h["Close"].shift(1)).abs()
        h["L-PC"] = (h["Low"] - h["Close"].shift(1)).abs()
        h["TR"] = h[["H-L", "H-PC", "L-PC"]].max(axis=1)
        atr = round(float(h["TR"].tail(14).mean()), 2)

        return pivots, atr
    except Exception as e:
        print(f"Error calculando pivots/ATR: {e}")
        return None, None


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_in_cooldown(alert_key, state, now, hours):
    last_str = state.get(alert_key)
    if not last_str:
        return False
    try:
        return (now - datetime.fromisoformat(last_str)) < timedelta(hours=hours)
    except Exception:
        return False


def position_vs_level(price, level_price):
    """Devuelve descripción textual de la posición del precio."""
    diff = price - level_price
    if abs(diff) < 1:
        return "justo en"
    elif diff < 0:
        return "por debajo de"
    else:
        return "por encima de"


def check_alerts(price, rsi, pivots, state):
    """Detecta alertas de tipo SETUP (prioridad) o PROXIMIDAD."""
    alerts = []
    now = datetime.now(timezone.utc)

    for level_name, level_price in pivots.items():
        distance = abs(price - level_price)

        # Si está fuera del rango de proximidad, ignorar
        if distance > PROXIMITY_TOLERANCE_PTS:
            continue

        # Comprobar primero si hay condiciones de SETUP
        setup_direction = None
        if distance <= SETUP_TOLERANCE_PTS:
            if level_name in ("S1", "S2") and rsi < RSI_OVERSOLD:
                setup_direction = "BUY"
            elif level_name in ("R1", "R2") and rsi > RSI_OVERBOUGHT:
                setup_direction = "SELL"
            elif level_name == "PP":
                if rsi < RSI_OVERSOLD:
                    setup_direction = "BUY"
                elif rsi > RSI_OVERBOUGHT:
                    setup_direction = "SELL"

        if setup_direction:
            # Alerta SETUP (más prioritaria)
            setup_key = f"SETUP_{setup_direction}_{level_name}"
            if not is_in_cooldown(setup_key, state, now, SETUP_COOLDOWN_HOURS):
                alerts.append({
                    "kind": "SETUP",
                    "type": setup_direction,
                    "level": level_name,
                    "level_price": level_price,
                    "current_price": round(price, 2),
                    "rsi": round(rsi, 1),
                    "distance": round(distance, 2),
                    "key": setup_key,
                })
        else:
            # Alerta de PROXIMIDAD (sin condición RSI)
            prox_key = f"PROX_{level_name}"
            if not is_in_cooldown(prox_key, state, now, PROXIMITY_COOLDOWN_HOURS):
                alerts.append({
                    "kind": "PROXIMITY",
                    "level": level_name,
                    "level_price": level_price,
                    "current_price": round(price, 2),
                    "rsi": round(rsi, 1),
                    "distance": round(distance, 2),
                    "position": position_vs_level(price, level_price),
                    "key": prox_key,
                })
    return alerts


def send_alert(alert, atr):
    """Envía alerta formateada a Telegram."""
    now_madrid = datetime.now(MADRID_TZ).strftime("%H:%M")

    if alert["kind"] == "SETUP":
        emoji = "🟢" if alert["type"] == "BUY" else "🔴"
        rsi_state = "sobrevendido" if alert["type"] == "BUY" else "sobrecomprado"
        msg = (
            f"{emoji} *SETUP {alert['type']} XAU/USD* — {now_madrid}\n\n"
            f"Nivel: *{alert['level']}* en {alert['level_price']}\n"
            f"Precio actual: {alert['current_price']}\n"
            f"Distancia: {alert['distance']} pts\n"
            f"RSI(14) M5: *{alert['rsi']}* ({rsi_state})\n"
        )
        if atr:
            msg += f"ATR(14): {atr} pts\n"
        msg += f"\n_Setup completo: precio en {alert['level']} + RSI {rsi_state}_"
    else:  # PROXIMITY
        msg = (
            f"📍 *Acercamiento a {alert['level']}* — {now_madrid}\n\n"
            f"Nivel: {alert['level']} en {alert['level_price']}\n"
            f"Precio: {alert['current_price']} ({alert['position']} {alert['level']})\n"
            f"Distancia: {alert['distance']} pts\n"
            f"RSI(14) M5: {alert['rsi']}\n\n"
            f"_Vigila el nivel — sin confirmación de RSI extremo_"
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")


def cleanup_old_state(state):
    """Limpia entradas más antiguas de 24h."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cleaned = {}
    for k, v in state.items():
        try:
            if datetime.fromisoformat(v) > cutoff:
                cleaned[k] = v
        except Exception:
            continue
    return cleaned


def main():
    state = load_state()

    price, rsi = get_price_and_rsi()
    pivots, atr = get_pivots_and_atr()

    if price is None or pivots is None:
        print("Sin datos disponibles")
        return

    print(f"Precio: {price:.2f} | RSI(M5): {rsi:.1f}")
    print(f"Pivots: {pivots}")
    print(f"ATR(14): {atr}")

    alerts = check_alerts(price, rsi, pivots, state)

    if alerts:
        now_iso = datetime.now(timezone.utc).isoformat()
        for alert in alerts:
            print(f"→ {alert['kind']}: {alert['key']}")
            send_alert(alert, atr)
            state[alert["key"]] = now_iso
    else:
        print("Sin alertas")

    state = cleanup_old_state(state)
    save_state(state)


if __name__ == "__main__":
    main()
