import os
import feedparser
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from groq import Groq

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

COINS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "ENA": ["ethena", "ena"],
    "STRK": ["starknet", "strk", "stark"],
    "NOT": ["notcoin", "not"],
    "TON": ["toncoin", "telegram open network", "the open network", "$ton"],
    "NEAR": ["near protocol", "near"],
    "OP": ["optimism", "op token"],
    "KAS": ["kaspa", "kas"],
    "ARB": ["arbitrum", "arb"],
    "TIA": ["celestia", "$tia"],
    "ZIL": ["zilliqa", "zil"],
    "SOL": ["solana", "sol"]
}

COIN_ORDER = ["BTC", "ETH", "SOL", "ENA", "STRK", "NOT", "TON",
              "NEAR", "OP", "KAS", "ARB", "TIA", "ZIL"]

COIN_TO_GECKO = {
    "BTC": "bitcoin", "ETH": "ethereum", "ENA": "ethena",
    "STRK": "starknet", "NOT": "notcoin", "TON": "the-open-network",
    "NEAR": "near", "OP": "optimism", "KAS": "kaspa",
    "ARB": "arbitrum", "TIA": "celestia", "ZIL": "zilliqa", "SOL": "solana"
}

# Пары для Binance (для загрузки свечей)
COIN_TO_BINANCE = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
    "ENA": "ENAUSDT", "STRK": "STRKUSDT", "NOT": "NOTUSDT",
    "TON": "TONUSDT", "NEAR": "NEARUSDT", "OP": "OPUSDT",
    "KAS": "KASUSDT", "ARB": "ARBUSDT", "TIA": "TIAUSDT",
    "ZIL": "ZILUSDT"
}

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://cryptoslate.com/feed/",
    "https://cointelegraph.com/rss",
    "https://theblock.co/rss.xml",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://cryptopotato.com/feed/",
    "https://ambcrypto.com/feed/",
    "https://beincrypto.com/feed/",
    "https://u.today/rss",
    "https://cryptobriefing.com/feed/",
    "https://coinjournal.net/feed/",
]

MAX_MESSAGE_LEN = 3900
MOVE_THRESHOLD_24H = 20.0
NEWS_MAX_AGE_HOURS = 24
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
KLINE_LIMIT = 100  # сколько часовых свечей брать для расчёта индикаторов


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        print("Telegram status:", response.status_code)
        if response.status_code != 200:
            print("Telegram response:", response.text)
    except Exception as e:
        print("Ошибка отправки в Telegram:", e)


def get_news():
    all_entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_MAX_AGE_HOURS)
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:40]:
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    date_str = pub_dt.strftime("%d.%m %H:%M")
                else:
                    date_str = "дата неизвестна"
                all_entries.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:450],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", "Unknown"),
                    "date": date_str
                })
        except Exception as e:
            print(f"Ошибка RSS {url}: {e}")
    return all_entries


def filter_relevant_news(entries):
    grouped = {}
    for entry in entries:
        text = (entry["title"] + " " + entry["summary"]).lower()
        for coin, keywords in COINS.items():
            if any(kw in text for kw in keywords):
                grouped.setdefault(coin, []).append(entry)
    return grouped


def get_market_data(coins):
    """Один запрос: цена, изменение за 24ч, объём, капитализация."""
    gecko_ids = [COIN_TO_GECKO[c] for c in coins if c in COIN_TO_GECKO]
    if not gecko_ids:
        return {}
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(gecko_ids),
        "price_change_percentage": "24h",
        "sparkline": "false"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        result = {}
        gid_to_coin = {v: k for k, v in COIN_TO_GECKO.items()}
        for item in data:
            coin = gid_to_coin.get(item["id"])
            if coin:
                result[coin] = {
                    "price": item.get("current_price"),
                    "change_24h": item.get("price_change_percentage_24h"),
                    "volume": item.get("total_volume"),
                    "market_cap": item.get("market_cap")
                }
        return result
    except Exception as e:
        print("Ошибка получения рыночных данных:", e)
        return {}


def get_klines(coin, limit=KLINE_LIMIT):
    """Загрузка часовых свечей с Binance. Возвращает DataFrame или None."""
    symbol = COIN_TO_BINANCE.get(coin)
    if not symbol:
        return None
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None
        raw = r.json()
        df = pd.DataFrame(raw, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        print(f"Ошибка свечей {coin}: {e}")
        return None


def compute_indicators(df):
    """RSI(14), MACD(12,26,9), поддержка/сопротивление за 20 свечей."""
    if df is None or len(df) < 30:
        return None

    close = df["close"]

    # RSI(14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None

    # MACD
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = (macd_line - signal_line).iloc[-1]

    # Поддержка/сопротивление
    support = df["low"].rolling(20).min().iloc[-1]
    resistance = df["high"].rolling(20).max().iloc[-1]
    last_price = close.iloc[-1]

    return {
        "rsi": rsi_val,
        "macd_hist": macd_hist,
        "support": support,
        "resistance": resistance,
        "last_price": last_price
    }


def format_indicator_line(indicators):
    """Строка с техническими индикаторами."""
    if not indicators:
        return ""

    parts = []

    # RSI
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            rsi_note = "перекупленность"
        elif rsi <= 30:
            rsi_note = "перепроданность"
        else:
            rsi_note = "нейтрально"
        parts.append(f"RSI {rsi:.0f} ({rsi_note})")

    # MACD
    hist = indicators.get("macd_hist")
    if hist is not None:
        direction = "бычий" if hist > 0 else "медвежий"
        parts.append(f"MACD {hist:+.4g} ({direction})")

    # Поддержка/сопротивление
    support = indicators.get("support")
    resistance = indicators.get("resistance")
    last = indicators.get("last_price")
    if support and resistance and last and support > 0:
        if last < 1:
            parts.append(f"поддержка ${support:.4f} / сопротивление ${resistance:.4f}")
        else:
            parts.append(f"поддержка ${support:,.2f} / сопротивление ${resistance:,.2f}")

    if not parts:
        return ""
    return "📊 " + " · ".join(parts) + "\n"


def format_liquidity_line(market_info):
    """Ликвидность по отношению объёма к капитализации."""
    if not market_info:
        return ""
    volume = market_info.get("volume")
    market_cap = market_info.get("market_cap")
    if not volume or not market_cap or market_cap == 0:
        return ""

    ratio = volume / market_cap

    if ratio >= 0.1:
        level = "высокая"
        icon = "🟢"
    elif ratio >= 0.03:
        level = "средняя"
        icon = "🟡"
    else:
        level = "низкая"
        icon = "🔴"

    vol_str = f"${volume/1e6:.1f}M" if volume < 1e9 else f"${volume/1e9:.2f}B"
    return f"💧 Ликвидность: {icon} {level} (объём 24ч {vol_str})\n"


def format_price_line(coin, market_info):
    if not market_info or market_info.get("price") is None:
        return "💰 цена недоступна"
    price = market_info["price"]
    change_24 = market_info.get("change_24h") or 0
    sign = "+" if change_24 >= 0 else ""
    arrow = "🟢" if change_24 >= 0 else "🔴"
    if price < 1:
        price_str = f"${price:.4f}"
    else:
        price_str = f"${price:,.2f}"
    return f"💰 {price_str} {arrow} {sign}{change_24:.2f}% (24ч)"


def _call_groq(prompt, max_tokens=800, temperature=0.2):
    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens
    )
    return (completion.choices[0].message.content or "").strip()


def analyze_coin(coin, news_list):
    if not news_list:
        return None
    news_list = news_list[:6]
    news_text = ""
    for i, n in enumerate(news_list, 1):
        news_text += f"\n{i}. Источник: {n['source']}, дата: {n['date']}\nЗаголовок: {n['title']}\nОписание: {n['summary']}\n"

    prompt = f"""Ты профессиональный крипто-аналитик. Проанализируй новости ТОЛЬКО по монете {coin}.

НОВОСТИ:
{news_text}

СТРОГИЕ ПРАВИЛА (нарушение недопустимо):
1. Весь ответ — ИСКЛЮЧИТЕЛЬНО на русском языке.
2. Английский текст запрещён. Заголовки новостей ПЕРЕВЕДИ на русский. Единственные допустимые английские слова — тикер {coin} и названия компаний (Binance, Coinbase, Ledger и т.п.).
3. Пиши ТОЛЬКО про {coin}. Не упоминай другие монеты и тикеры.
4. НЕ используй символы ** и *. Только HTML-теги <b>...</b> для меток.
5. Соблюдай грамматику русского языка. Проверь согласование рода, числа и падежа.
6. Объедини все новости в одну краткую сводку.
7. Формат источника строго: (Источник, ДД.ММ ЧЧ:ММ).
8. Максимум 5 строк.

ФОРМАТ ОТВЕТА (строго):

<b>Суть:</b> одна короткая фраза на русском с источником и датой
<b>Тон:</b> Бычий / Медвежий / Нейтральный
<b>Важность:</b> X/10
<b>Влияние на цену:</b> коротко и грамматически верно
<b>Рекомендация:</b> одно короткое действие

Начни ответ сразу с метки <b>Суть:</b> без вступлений.
"""
    try:
        text = _call_groq(prompt)
        if not text:
            text = _call_groq(prompt, temperature=0.4)
        return text or None
    except Exception as e:
        print(f"[ERROR] Groq для {coin}: {e}")
        return None


def build_coin_block(coin, news, market_info):
    block = f"\n🪙 <b>{coin}</b>\n"
    block += format_price_line(coin, market_info) + "\n"

    # Технические индикаторы
    klines = get_klines(coin)
    indicators = compute_indicators(klines)
    indicator_line = format_indicator_line(indicators)
    if indicator_line:
        block += indicator_line

    # Ликвидность
    liq_line = format_liquidity_line(market_info)
    if liq_line:
        block += liq_line

    block += "\n"

    analysis = analyze_coin(coin, news)
    if analysis:
        block += analysis + "\n"
    else:
        block += "<i>Свежих значимых новостей за 24ч нет.</i>\n"
    return block


def send_long_message(header, blocks):
    """Разбивает отчёт на несколько сообщений, не режет блоки посередине."""
    messages = []
    current = header
    for block in blocks:
        if len(block) > MAX_MESSAGE_LEN:
            if current.strip():
                messages.append(current)
                current = ""
            messages.append(block[:MAX_MESSAGE_LEN - 40] + "\n… (обрезано)\n")
            continue
        if len(current) + len(block) <= MAX_MESSAGE_LEN:
            current += block
        else:
            messages.append(current)
            current = block
    if current.strip():
        messages.append(current)

    for i, m in enumerate(messages, 1):
        print(f"Отправка {i}/{len(messages)}, длина {len(m)}")
        send_telegram(m)


def main():
    print(f"Запуск бота: {datetime.now(timezone.utc)}")

    entries = get_news()
    grouped = filter_relevant_news(entries)
    print(f"Монет с новостями: {len(grouped)}")

    all_coins = [c for c in COIN_ORDER if c in COIN_TO_GECKO]
    market_data = get_market_data(all_coins)
    print(f"Получены рыночные данные: {len(market_data)}")

    # Срочные оповещения при изменении >= 20% за 24ч
    for coin, info in market_data.items():
        change = info.get("change_24h")
        if change is None or abs(change) < MOVE_THRESHOLD_24H:
            continue
        price = info.get("price")
        if price is None:
            continue
        price_str = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
        if change > 0:
            header = f"🚀 <b>СРОЧНО: резкий рост {coin}</b>"
            arrow_line = f"📈 За 24ч: +{change:.2f}%"
        else:
            header = f"🚨 <b>СРОЧНО: резкое падение {coin}</b>"
            arrow_line = f"📉 За 24ч: {change:.2f}%"
        send_telegram(f"{header}\n\n💰 Цена: {price_str}\n{arrow_line}\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')} UTC")

    header = (f"<b>📡 Крипто-новости</b>\n"
              f"{datetime.now().strftime('%d.%m.%Y %H:%M')} UTC\n"
              f"<i>глубина: последние {NEWS_MAX_AGE_HOURS}ч · RSI/MACD/ликвидность</i>\n")

    blocks = []
    for coin in COIN_ORDER:
        news = grouped.get(coin, [])
        block = build_coin_block(coin, news, market_data.get(coin))
        blocks.append(block)

    send_long_message(header, blocks)
    print("Отчёт отправлен")


if __name__ == "__main__":
    main()
