import os
import feedparser
import requests
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
    "TON": ["toncoin", "ton", "telegram open network"],
    "NEAR": ["near protocol", "near"],
    "OP": ["optimism", "op token"],
    "KAS": ["kaspa", "kas"],
    "ARB": ["arbitrum", "arb"],
    "TIA": ["celestia", "tia"],
    "ZIL": ["zilliqa", "zil"],
    "SOL": ["solana", "sol"]
}

COIN_ORDER = ["BTC", "ETH", "SOL", "ENA", "STRK", "NOT", "TON",
              "NEAR", "OP", "KAS", "ARB", "TIA", "ZIL"]

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
    "https://cryptopotato.com/feed/",
    "https://ambcrypto.com/feed/",
    "https://beincrypto.com/feed/",
    "https://u.today/rss",
    "https://cryptobriefing.com/feed/",
    "https://coinjournal.net/feed/",
]

MAX_MESSAGE_LEN = 3900
MOVE_THRESHOLD_24H = 20.0
NEWS_MAX_AGE_HOURS = 24  # Глубина: новости не старше 24 часов

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
    """Собирает новости, фильтрует по времени и сохраняет дату/источник."""
    all_entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_MAX_AGE_HOURS)
    
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            # Увеличиваем глубину: смотрим 40 записей из каждой ленты
            for entry in feed.entries[:40]:
                # Проверяем дату публикации
                published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue  # слишком старая новость
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

def get_prices(coins):
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
        result = {}
        for coin in coins:
            gid = COIN_TO_GECKO.get(coin)
            if gid and gid in data:
                result[coin] = {
                    "price": data[gid].get("usd"),
                    "change_24h": data[gid].get("usd_24h_change")
                }
        return result
    except Exception as e:
        print("Ошибка получения цен:", e)
        return {}

def check_big_moves(prices):
    for coin, info in prices.items():
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

        msg = (
            f"{header}\n\n"
            f"💰 Цена: {price_str}\n"
            f"{arrow_line}\n"
            f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')} UTC"
        )
        send_telegram(msg)

def format_price_line(coin, price_info):
    if not price_info or price_info.get("price") is None:
        return "💰 цена недоступна"
    price = price_info["price"]
    change_24 = price_info.get("change_24h") or 0
    sign = "+" if change_24 >= 0 else ""
    arrow = "🟢" if change_24 >= 0 else "🔴"
    if price < 1:
        price_str = f"${price:.4f}"
    else:
        price_str = f"${price:,.2f}"
    return f"💰 {price_str} {arrow} {sign}{change_24:.2f}% (24ч)"

def analyze_coin(coin, news_list, price_info):
    """Анализ всех новостей монеты с указанием даты и источника."""
    if not news_list:
        return (f"<b>Суть:</b> новых значимых новостей по {coin} нет.\n"
                f"<b>Тон:</b> Нейтральный\n"
                f"<b>Важность:</b> 2/10\n"
                f"<b>Влияние на цену:</b> движение в основном за общим рынком.\n"
                f"<b>Рекомендация:</b> наблюдать, резких действий не требуется.")

    news_list = news_list[:6]

    prompt = f"""Ты профессиональный крипто-аналитик. Проанализируй ТОЛЬКО монету {coin}.

Новости по {coin} (за последние 24 часа):
"""
    for i, n in enumerate(news_list, 1):
        prompt += f"\n{i}. [{n['source']}, {n['date']}] {n['title']}\n{n['summary']}\n"

    prompt += f"""

ЖЁСТКИЕ ПРАВИЛА ВЫВОДА:
1. Отвечай ТОЛЬКО на русском языке. Английский запрещён.
2. Пиши ТОЛЬКО про {coin}. Не упоминай другие монеты и тикеры.
3. НЕ используй символы ** и * для выделения. Только HTML <b>метки</b>.
4. Проанализируй ВСЕ переданные новости и объедини их в одну краткую сводку.
5. Обязательно укажи, КАК это повлияет на цену.
6. В разделе "Суть" укажи источник и дату главной новости, например: (CoinDesk, 09.10 14:30).
7. Максимум 6 строк.

Формат (строго):

<b>Суть:</b> одна короткая фраза, объединяющая главные новости, с указанием источника и даты
<b>Тон:</b> Бычий / Медвежий / Нейтральный
<b>Важность:</b> X/10
<b>Влияние на цену:</b> коротко, что будет с ценой (рост/падение/боковик и почему)
<b>Рекомендация:</b> одно короткое действие
"""

    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        text = completion.choices[0].message.content
        if not text or not text.strip():
            return (f"<b>Суть:</b> ИИ не вернул анализ по {coin}.\n"
                    f"<b>Тон:</b> Нейтральный\n"
                    f"<b>Важность:</b> 2/10\n"
                    f"<b>Влияние на цену:</b> неопределённо.\n"
                    f"<b>Рекомендация:</b> наблюдать.")
        return text.strip()
    except Exception as e:
        return (f"<b>Суть:</b> ошибка анализа ИИ по {coin}.\n"
                f"<b>Тон:</b> Нейтральный\n"
                f"<b>Важность:</b> 2/10\n"
                f"<b>Влияние на цену:</b> неопределённо.\n"
                f"<b>Рекомендация:</b> наблюдать.")

def build_coin_block(coin, news, price_info):
    block = f"\n🪙 <b>{coin}</b>\n"
    block += format_price_line(coin, price_info) + "\n\n"
    block += analyze_coin(coin, news, price_info) + "\n"
    return block

def send_long_message(header, blocks):
    messages = []
    current = header

    for block in blocks:
        if len(block) > MAX_MESSAGE_LEN:
            if current.strip():
                messages.append(current)
                current = ""
            chunk = block[:MAX_MESSAGE_LEN - 30] + "\n… (обрезано)\n"
            messages.append(chunk)
            continue

        if len(current) + len(block) <= MAX_MESSAGE_LEN:
            current += block
        else:
            messages.append(current)
            current = block

    if current.strip():
        messages.append(current)

    for m in messages:
        send_telegram(m)

def main():
    print(f"Запуск бота: {datetime.now(timezone.utc)}")

    entries = get_news()
    grouped = filter_relevant_news(entries)
    print(f"Монет с новостями: {len(grouped)}")

    all_coins = [c for c in COIN_ORDER if c in COIN_TO_GECKO]
    prices = get_prices(all_coins)

    check_big_moves(prices)

    header = (f"<b>📡 Крипто-новости</b>\n"
              f"{datetime.now().strftime('%d.%m.%Y %H:%M')} UTC\n"
              f"<i>глубина: последние {NEWS_MAX_AGE_HOURS}ч</i>\n")

    blocks = []
    for coin in COIN_ORDER:
        news = grouped.get(coin, [])
        block = build_coin_block(coin, news, prices.get(coin))
        blocks.append(block)

    send_long_message(header, blocks)
    print("Отчёт отправлен")

if __name__ == "__main__":
    main()
