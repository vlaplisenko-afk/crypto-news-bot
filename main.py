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
    relevant = []
    for entry in entries:
        text = (entry["title"] + " " + entry["summary"]).lower()
        matched_coins = []
        for coin, keywords in COINS.items():
            if any(kw in text for kw in keywords):
                matched_coins.append(coin)
        if matched_coins:
            entry["coins"] = list(set(matched_coins))
            relevant.append(entry)
    return relevant

def analyze_with_ai(news_list):
    if not news_list:
        return "За последний час важных новостей по твоим монетам почти нет."

    news_list = news_list[:10]

    prompt = f"""Ты профессиональный крипто-аналитик. Сделай краткий умный отчёт на русском языке.

Новости:
"""
    for i, n in enumerate(news_list, 1):
        prompt += f"\n{i}. [{', '.join(n['coins'])}] {n['title']}\n{n['summary']}\nИсточник: {n['source']}\n"

    prompt += """

Формат ответа строго такой:

🔥 <b>Краткий обзор</b>

Для каждой важной новости пиши:
• Монеты: ...
• Суть: 1-2 предложения
• Тон: Бычий / Медвежий / Нейтральный
• Важность: от 1 до 10
• Влияние на цену: коротко
• Рекомендация: ...

В конце:
📊 <b>Общий вывод</b>
• Какие монеты сейчас в фокусе
• Общий настрой
• Есть ли срочные события

Пиши коротко и по делу. Используй HTML <b> для заголовков.
"""

    print("=== DEBUG: Использую модель llama-3.1-8b-instant ===")

    client = Groq(api_key=GROQ_API_KEY)

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=1600
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Ошибка анализа ИИ: {e}"

def main():
    print(f"Запуск бота: {datetime.now(timezone.utc)}")

    entries = get_news()
    relevant = filter_relevant_news(entries)
    print(f"Найдено релевантных новостей: {len(relevant)}")

    report = analyze_with_ai(relevant)

    header = f"<b>📡 Крипто-новости</b>\n{datetime.now().strftime('%d.%m.%Y %H:%M')} UTC\n\n"
    full_message = header + report

    if len(full_message) > 4000:
        full_message = full_message[:3900] + "\n\n... (обрезано)"

    send_telegram(full_message)
    print("Отчёт отправлен")

if __name__ == "__main__":
    main()
