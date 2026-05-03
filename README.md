# Briefing diario XAU/USD por Telegram

Sistema automático que cada mañana te envía a Telegram:
- Calendario económico USD del día (alta importancia, hora Madrid)
- Estado de XAU/USD, DXY y US10Y
- Noticias geopolíticas y de oro de las últimas 24h
- Síntesis con IA filtrando lo relevante para el oro
- Niveles a vigilar

---

## 1. Crear el bot de Telegram (5 minutos)

1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot` y sigue las instrucciones (nombre + username terminado en `bot`)
3. BotFather te dará un **token** tipo `123456789:ABCdef...` → cópialo, es tu `TELEGRAM_BOT_TOKEN`
4. Ahora necesitas tu `TELEGRAM_CHAT_ID`:
   - Abre tu nuevo bot en Telegram y envíale cualquier mensaje (ej. "hola")
   - Visita en el navegador: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   - Busca `"chat":{"id":XXXXXXXX` → ese número es tu `TELEGRAM_CHAT_ID`

## 2. Conseguir API key de Anthropic (opcional pero recomendado)

Sin esto el briefing funciona, pero solo te llega data cruda sin síntesis. Con esto Claude te resume y filtra.

1. Crea cuenta en https://console.anthropic.com
2. Ve a "API Keys" → crea una key
3. Carga 5€ de crédito (con Haiku 4.5, un briefing diario cuesta menos de 1 céntimo, así que con 5€ tienes para >1 año)

## 3. Probar en local

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tus claves
python briefing.py
```

Si todo va bien, recibes el briefing en Telegram en segundos.

## 4. Automatizarlo cada mañana — opciones

### Opción A: GitHub Actions (gratis, recomendada)
1. Crea un repo privado en GitHub y sube los archivos
2. Mueve `daily_briefing.yml` a `.github/workflows/daily_briefing.yml`
3. Ve a Settings → Secrets and variables → Actions → añade los 3 secretos:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `ANTHROPIC_API_KEY`
4. Listo. Se ejecuta automáticamente lunes-viernes a las 07:00 hora Madrid (invierno) / 08:00 (verano).

Para cambiar la hora edita la línea `cron: '0 6 * * 1-5'` (está en UTC).

### Opción B: Tu propio ordenador con cron (Linux/Mac)
```bash
crontab -e
# Añade esta línea (07:00 hora local):
0 7 * * 1-5 cd /ruta/al/proyecto && /usr/bin/python3 briefing.py
```
Solo funciona si el ordenador está encendido a esa hora.

### Opción C: VPS o Raspberry Pi
Igual que opción B pero en una máquina que esté siempre encendida.

---

## Personalización

**Cambiar las fuentes de noticias:** edita el dict `feeds` en `get_news()`.

**Añadir más activos** (plata, BTC, S&P): añade tickers al dict en `get_market_data()`. Por ejemplo:
- Plata: `SI=F`
- S&P 500: `^GSPC`
- VIX: `^VIX`
- Bitcoin: `BTC-USD`

**Filtrar más eventos:** en `get_economic_calendar()` puedes incluir EUR/CNY/JPY si quieres más contexto, o eventos `Medium` además de `High`.

**Cambiar el modelo de IA:** en `synthesize_with_claude()`, puedes usar `claude-sonnet-4-6` para mejor calidad (≈10x más caro pero igualmente barato a este volumen).

**Cambiar el prompt:** en la misma función, ajusta el bloque `INSTRUCCIONES` para que el briefing tenga el enfoque que tú prefieras (más técnico, más fundamental, niveles específicos que tú sigas, etc.).

---

## Coste mensual estimado
- Telegram: 0€
- ForexFactory + yfinance + RSS: 0€
- Claude Haiku 4.5 (briefing diario): ~0.20€/mes
- GitHub Actions: 0€ (dentro de los minutos gratuitos)

**Total: prácticamente gratis.**
