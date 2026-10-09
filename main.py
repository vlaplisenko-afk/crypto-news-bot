import os
import feedparser
import requests
from datetime import datetime, timezone
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
    "TON": ["toncoin", "ton", "telegram open network"],
    "NEAR": ["near protocol", "near"],
    "OP": ["optimism", "op token"],
    "KAS": ["kaspa", "kas"],
    "ARB": ["arbitrum", "arb"],
    "TIA": ["celestia", "tia"],
    "ZIL": ["zilliqa", "zil"],
    "SOL": ["solana", "sol"]
}

# ID монет для CoinGecko
COIN_TO_GECKO = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "ENA": "ethena",
    "STRK": "starknet",
    "NOT": "notcoin",
    "TON": "the-open-network",
    "NEAR": "near",
    "OP": "optimism",
    "KAS": "kaspa",
    "ARB": "arbitrum",
    "TIA": "celestia",
    "ZIL": "zilliqa",
    "SOL": "solana"
}

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://cryptoslate.com/feed/",
    "https://cointelegraph.com/rss",
    "https://theblock.co/rss.xml",
    "https://bitcoinmagazine.com/.rss/full/",
]


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
        print("Telegram response:", response.text)
    except Exception as e:
        print("Ошибка отправки в Telegram:", e)


def get_news():
    all_entries = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                all_entries.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:450],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", "Unknown")
                })
        except Exception as e:
            print(f"Ошибка RSS {url}: {e}")
    return all_entries


def filter_relevant_news(entries):
    """Возвращает dict: {монета: [новости]}"""
    grouped = {}
    for entry in entries:
        text = (entry["title"] + " " + entry["summary"]).lower()
        for coin, keywords in COINS.items():
            if any(kw in text for kw in keywords):
                grouped.setdefault(coin, []).append(entry)
    return grouped


def get_prices(coins):
    """Получаем цены и изменение за 24ч через CoinGecko."""
    gecko_ids = [COIN_TO_GECKO[c] for c in coins if c in COIN_TO_GECKO]
    if not gecko_ids:
        return {}
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(gecko_ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        # обратное сопоставление gecko_id -> тикер
        result = {}
        for coin in coins:
            gid = COIN_TO_GECKO.get(coin)
            if gid and gid in data:
                result[coin] = {
                    "price": data[gid].get("usd"),
                    "change": data[gid].get("usd_24h_change")
                }
        return result
    except Exception as e:
        print("Ошибка получения цен:", e)
        return {}


def analyze_coin(coin, news_list, price_info):
    if not news_list:
        return None

    news_list = news_list[:6]

    price_line = ""
    if price_info and price_info.get("price") is not None:
        price = price_info["price"]
        change = price_info.get("change") or 0
        sign = "+" if change >= 0 else ""
        price_line = f"Текущая цена {coin}: ${price:,.2f} ({sign}{change:.2f}% за 24ч)\n\n"

    prompt = f"""Ты крипто-аналитик. Проанализируй ТОЛЬКО монету {coin}.

{price_line}Новости по {coin}:
"""
    for i, n in enumerate(news_list, 1):
        prompt += f"\n{i}. {n['title']}\n{n['summary']}\n"

    prompt += f"""

Правила вывода (строго):
- Пиши только про {coin}, не упоминай другие монеты
- НЕ используй символы ** и * для выделения
- Не дублируй заголовки новостей, дай выжимку
- Кратко, по делу, максимум 5-6 строк

Формат (строго):

Суть: одна короткая фраза по главной новости
Тон: Бычий / Медвежий / Нейтральный
Важность: X/10
Влияние: коротко о влиянии на цену
Рекомендация: одно короткое действие

Используй HTML <b>только</b> для меток (Суть, Тон, Важность, Влияние, Рекомендация).
"""

    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка анализа ИИ для {coin}: {e}"


def main():
    print(f"Запуск бота: {datetime.now(timezone.utc)}")

    entries = get_news()
    grouped = filter_relevant_news(entries)
    print(f"Монет с новостями: {len(grouped)}")

    if not grouped:
        send_telegram("📡 Крипто-новости\n\nЗа последнее время важных новостей по твоим монетам нет.")
        return

    prices = get_prices(list(grouped.keys()))

    header = f"<b>📡 Крипто-новости</b>\n{datetime.now().strftime('%d.%m.%Y %H:%M')} UTC\n"
    parts = [header]

    for coin, news in grouped.items():
        block = f"\n🪙 <b>{coin}</b>\n"

        p = prices.get(coin)
        if p and p.get("price") is not None:
            change = p.get("change") or 0
            sign = "+" if change >= 0 else ""
            arrow = "🟢" if change >= 0 else "🔴"
            block += f"💰 ${p['price']:,.2f} {arrow} {sign}{change:.2f}% (24ч)\n\n"
        else:
            block += "💰 цена недоступна\n\n"

        analysis = analyze_coin(coin, news, p)
        if analysis:
            block += analysis + "\n"

        parts.append(block)

    full_message = "\n".join(parts)

    if len(full_message) > 4000:
        full_message = full_message[:3900] + "\n\n... (обрезано)"

    send_telegram(full_message)
    print("Отчёт отправлен")


if __name__ == "__main__":
    main()
