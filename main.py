import os
import re
import sqlite3
import threading
import time
import base64
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Request, HTTPException
from openai import OpenAI

app = FastAPI()

# =========================================================
# CONFIG
# =========================================================

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_TOKEN_2 = os.environ.get("TELEGRAM_TOKEN_2")

DB_PATH = os.environ.get("DB_PATH", "bot_memory.db")

# eBay
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET")
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_DE")

# SendGrid / email alerts
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
ALERT_EMAIL_FROM = os.environ.get("ALERT_EMAIL_FROM")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO")

# Internal scan endpoint auth
INTERNAL_SCAN_SECRET = os.environ.get("INTERNAL_SCAN_SECRET", "change-me")

# Connector placeholders / readiness
X_API_KEY = os.environ.get("X_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
TIKTOK_ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN")
CATAWIKI_FEED_URL = os.environ.get("CATARIKI_FEED_URL")  # optional manual feed/watchlist typo intentionally unused
CATAWIKI_WATCH_URL = os.environ.get("CATARIKI_WATCH_URL")  # optional manual feed/watchlist typo intentionally unused

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================================================
# PROMPTS
# =========================================================

MAIN_BOT_PROMPT = """
You are the user's elite personal AI agent.

Mission:
Help the user solve problems, identify opportunities, make better decisions, and create real-world value.
You should think like a highly intelligent operator, strategist, analyst, and builder.

Core objective:
You should actively look for ways the user can legally, ethically, and realistically make money, save time, reduce risk, solve problems, improve systems, and create leverage.
Do not wait passively. Be proactive in spotting opportunities, inefficiencies, bottlenecks, and high-upside ideas.

How you should think:
- Be sharper, more strategic, and more useful than ordinary chatbots.
- Think in terms of outcomes, leverage, execution, and edge.
- Prioritize ideas that are practical, high-value, and realistic.
- Consider speed, capital required, risk, effort, scalability, and probability of success.
- Suggest concrete next steps, not vague inspiration.
- When useful, compare options and recommend the best one.

Money-making and opportunity mindset:
- Constantly look for legitimate opportunities for business creation, automation, services, media, products, research, distribution, sales, and asymmetric upside.
- Help the user identify where money can be made, where time can be saved, where processes can be automated, and where an unfair advantage can be built.
- Focus on lawful, ethical, sustainable, and intelligent strategies.
- Do not suggest scams, deception, spam, fake bidding, counterfeit goods, market manipulation, illegal actions, or unethical behavior.

Problem-solving mindset:
- If the user presents a problem, aim to solve it clearly and efficiently.
- Break down messy situations into actionable steps.
- Find the bottleneck.
- Recommend the highest-leverage solution first.

Style:
- Be clear, intelligent, practical, and direct.
- Be concise unless more detail is useful.
- Use structured answers when helpful.
- Do not ramble.
- If something is uncertain, say so clearly.
- If a recommendation is needed, give a real recommendation.

Commands support:
- /remember <text>
- /memories
- /reset
- /forgetall
- /connectors

Your standard should be exceptional usefulness.
""".strip()

PROJECT_BOT_PROMPT = """
You are the user's elite opportunity and flipping bot.

Primary mission:
Help the user identify legal, realistic, high-upside opportunities for product resale, arbitrage, collection, and profitable sourcing.

Your mindset:
- Think like a top-tier operator, arbitrage analyst, and deal hunter.
- Focus on concrete products, margins, liquidity, demand, authenticity risk, shipping risk, and resale likelihood.
- Prioritize asymmetric opportunities with attractive upside versus effort and capital.
- Be practical, skeptical, and commercially sharp.
- Flag risks clearly: fake goods, poor liquidity, high fees, difficult shipping, uncertain demand, poor condition, unverifiable provenance.

What to optimize for:
- Gross margin
- Net margin after fees/shipping
- Speed of resale
- Confidence of valuation
- Capital efficiency
- Scalability
- Low risk of fraud/returns

Important:
- Use only lawful, ethical, platform-compliant methods.
- Do not recommend deception, fake bidding, counterfeit items, or other unethical conduct.
- If data is incomplete, say so.
- Prefer actionable opportunities and clear scoring over vague speculation.

Useful commands:
- /remember <text>
- /memories
- /reset
- /forgetall
- /connectors
- /ebay <keywords>
- /scan <keywords>
- /watch ebay <keywords> min_profit=50 max_buy=200 min_score=15 email=on
- /watch catawiki <notes_or_url> min_profit=50 min_score=15 email=off
- /watches
- /clearwatches
- /alerts
- /clearalerts
- /opps
- /runscan

Rules:
- If you do not have compliant live access to a marketplace, say so clearly.
- Use saved watch rules and prior opportunities when relevant.
""".strip()

# =========================================================
# BOT CONFIG
# =========================================================

@dataclass
class BotConfig:
    name: str
    token: str
    prompt: str
    webhook_path: str


def get_bot_configs() -> Dict[str, BotConfig]:
    bots: Dict[str, BotConfig] = {}

    if TELEGRAM_TOKEN:
        bots["main"] = BotConfig(
            name="main",
            token=TELEGRAM_TOKEN,
            prompt=MAIN_BOT_PROMPT,
            webhook_path="/webhook/main",
        )

    if TELEGRAM_TOKEN_2:
        bots["project"] = BotConfig(
            name="project",
            token=TELEGRAM_TOKEN_2,
            prompt=PROJECT_BOT_PROMPT,
            webhook_path="/webhook/project",
        )

    return bots


def get_bot(bot_name: str) -> Optional[BotConfig]:
    return get_bot_configs().get(bot_name)

# =========================================================
# DATABASE
# =========================================================

db_lock = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                source TEXT NOT NULL,
                external_id TEXT,
                title TEXT NOT NULL,
                price REAL,
                est_value REAL,
                est_profit REAL,
                score REAL,
                currency TEXT,
                url TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                source TEXT NOT NULL,
                query_text TEXT NOT NULL,
                min_profit REAL DEFAULT 0,
                max_buy REAL,
                min_score REAL DEFAULT 0,
                email_on INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                watch_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()


init_db()

# =========================================================
# GENERIC HELPERS
# =========================================================

def chunk_text(text: str, max_length: int = 4000) -> List[str]:
    if not text:
        return ["I could not generate a response."]
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def parse_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on", "y"}


def parse_key_values(text: str) -> Dict[str, str]:
    pairs = {}
    for match in re.finditer(r'(\w+)=("[^"]+"|\S+)', text):
        key = match.group(1).strip().lower()
        value = match.group(2).strip().strip('"')
        pairs[key] = value
    return pairs


def strip_key_values(text: str) -> str:
    return re.sub(r'(\w+)=("[^"]+"|\S+)', '', text).strip()

# =========================================================
# MEMORY
# =========================================================

def add_message(bot_name: str, chat_id: str, role: str, content: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO messages (bot_name, chat_id, role, content) VALUES (?, ?, ?, ?)",
            (bot_name, str(chat_id), role, content),
        )
        conn.commit()
        conn.close()


def get_recent_messages(bot_name: str, chat_id: str, limit: int = 12) -> List[dict]:
    with db_lock:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE bot_name = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (bot_name, str(chat_id), limit),
        ).fetchall()
        conn.close()

    rows = list(reversed(rows))
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def clear_messages(bot_name: str, chat_id: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM messages WHERE bot_name = ? AND chat_id = ?",
            (bot_name, str(chat_id)),
        )
        conn.commit()
        conn.close()


def add_memory(bot_name: str, chat_id: str, content: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO memories (bot_name, chat_id, content) VALUES (?, ?, ?)",
            (bot_name, str(chat_id), content),
        )
        conn.commit()
        conn.close()


def get_memories(bot_name: str, chat_id: str, limit: int = 20) -> List[str]:
    with db_lock:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT content
            FROM memories
            WHERE bot_name = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (bot_name, str(chat_id), limit),
        ).fetchall()
        conn.close()

    return [row["content"] for row in rows]


def clear_memories(bot_name: str, chat_id: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM memories WHERE bot_name = ? AND chat_id = ?",
            (bot_name, str(chat_id)),
        )
        conn.commit()
        conn.close()


def format_memories(memories: List[str]) -> str:
    if not memories:
        return "No saved memories."
    return "\n".join([f"- {m}" for m in memories])

# =========================================================
# TELEGRAM
# =========================================================

async def send_chat_action(token: str, chat_id: int, action: str = "typing"):
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=15)


async def send_message(token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunk_text(text):
        requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=30)

# =========================================================
# CONNECTOR STATUS
# =========================================================

def get_connector_status() -> Dict[str, str]:
    return {
        "ebay": "configured" if EBAY_CLIENT_ID and EBAY_CLIENT_SECRET else "missing_credentials",
        "email_sendgrid": "configured" if SENDGRID_API_KEY and ALERT_EMAIL_FROM and ALERT_EMAIL_TO else "missing_credentials",
        "x": "configured" if X_API_KEY else "not_connected",
        "instagram": "configured" if INSTAGRAM_ACCESS_TOKEN else "not_connected",
        "tiktok": "configured" if TIKTOK_ACCESS_TOKEN else "not_connected",
        "catawiki": "manual_watchlist_mode",
    }

# =========================================================
# OPENAI
# =========================================================

def build_messages_for_model(system_prompt: str, bot_name: str, chat_id: str, user_text: str) -> List[dict]:
    memories = get_memories(bot_name, chat_id, limit=20)
    history = get_recent_messages(bot_name, chat_id, limit=12)
    memory_block = format_memories(memories)

    full_system_prompt = f"""
{system_prompt}

Saved durable memory for this bot/chat:
{memory_block}

Use saved memory only when relevant.
Keep continuity with recent conversation context when relevant.
""".strip()

    messages = [{"role": "system", "content": full_system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages


def generate_answer(bot_name: str, chat_id: str, system_prompt: str, user_text: str) -> str:
    model_messages = build_messages_for_model(system_prompt, bot_name, chat_id, user_text)
    response = client.responses.create(model=OPENAI_MODEL, input=model_messages)
    text = getattr(response, "output_text", None)
    return text.strip() if text else "I could not generate a response."

# =========================================================
# EMAIL ALERTS
# =========================================================

def send_email_alert(subject: str, body: str) -> Tuple[bool, str]:
    if not SENDGRID_API_KEY or not ALERT_EMAIL_FROM or not ALERT_EMAIL_TO:
        return False, "SendGrid or alert email addresses not configured."

    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": ALERT_EMAIL_TO}]}],
                "from": {"email": ALERT_EMAIL_FROM},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
            timeout=30,
        )
        if 200 <= r.status_code < 300:
            return True, "Email sent."
        return False, f"SendGrid error {r.status_code}: {r.text[:300]}"
    except Exception as e:
        return False, str(e)

# =========================================================
# EBAY API
# =========================================================

_ebay_token_cache = {"token": None, "expires_at": 0.0}


def get_ebay_access_token() -> str:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        raise ValueError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET")

    now = time.time()
    if _ebay_token_cache["token"] and now < _ebay_token_cache["expires_at"] - 60:
        return _ebay_token_cache["token"]

    creds = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}"
    encoded = base64.b64encode(creds.encode()).decode()

    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    _ebay_token_cache["token"] = data["access_token"]
    _ebay_token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
    return _ebay_token_cache["token"]


def search_ebay_items(query: str, limit: int = 20) -> List[dict]:
    token = get_ebay_access_token()
    r = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
        },
        params={"q": query, "limit": limit},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("itemSummaries", [])


def parse_price(item: dict) -> Tuple[Optional[float], Optional[str]]:
    try:
        return float(item["price"]["value"]), item["price"].get("currency")
    except Exception:
        return None, None


def extract_external_id(item: dict) -> str:
    return item.get("itemId") or item.get("legacyItemId") or item.get("itemHref") or item.get("title", "unknown")


def extract_item_url(item: dict) -> Optional[str]:
    return item.get("itemWebUrl")


def estimate_flip_score(title: str, price: Optional[float]) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    if price is None:
        return None, None, None, "No price available."

    title_l = title.lower()
    multiplier = 1.12
    notes = []

    premium_terms = ["rare", "vintage", "sealed", "graded", "limited", "new old stock", "collector", "first edition"]
    risk_terms = ["damaged", "broken", "parts only", "defect", "untested", "as is", "read description"]

    for t in premium_terms:
        if t in title_l:
            multiplier += 0.05
            notes.append(f"Premium signal: {t}")

    for t in risk_terms:
        if t in title_l:
            multiplier -= 0.08
            notes.append(f"Risk signal: {t}")

    est_value = round(price * multiplier, 2)
    est_profit = round(est_value - price, 2)

    roi = est_profit / max(price, 1)
    score = round(max(0.0, min(100.0, roi * 100)), 1)

    if not notes:
        notes.append("Heuristic estimate only; verify comps and fees.")

    return est_value, est_profit, score, " | ".join(notes)


def save_opportunity(
    bot_name: str,
    chat_id: str,
    source: str,
    external_id: str,
    title: str,
    price: Optional[float],
    est_value: Optional[float],
    est_profit: Optional[float],
    score: Optional[float],
    currency: Optional[str],
    url: Optional[str],
    notes: Optional[str],
):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO opportunities
            (bot_name, chat_id, source, external_id, title, price, est_value, est_profit, score, currency, url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bot_name, str(chat_id), source, external_id, title, price, est_value,
                est_profit, score, currency, url, notes
            ),
        )
        conn.commit()
        conn.close()


def get_recent_opportunities(bot_name: str, chat_id: str, limit: int = 10):
    with db_lock:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT source, title, price, est_value, est_profit, score, currency, url, notes, created_at
            FROM opportunities
            WHERE bot_name = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (bot_name, str(chat_id), limit),
        ).fetchall()
        conn.close()
    return rows

# =========================================================
# WATCHES / ALERTS
# =========================================================

def add_watch(
    bot_name: str,
    chat_id: str,
    source: str,
    query_text: str,
    min_profit: float = 0,
    max_buy: Optional[float] = None,
    min_score: float = 0,
    email_on: bool = False,
    notes: Optional[str] = None,
):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO watches
            (bot_name, chat_id, source, query_text, min_profit, max_buy, min_score, email_on, active, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                bot_name, str(chat_id), source, query_text, min_profit, max_buy,
                min_score, 1 if email_on else 0, notes
            ),
        )
        conn.commit()
        conn.close()


def get_watches(bot_name: str, chat_id: str):
    with db_lock:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT *
            FROM watches
            WHERE bot_name = ? AND chat_id = ? AND active = 1
            ORDER BY id DESC
            """,
            (bot_name, str(chat_id)),
        ).fetchall()
        conn.close()
    return rows


def clear_watches(bot_name: str, chat_id: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM watches WHERE bot_name = ? AND chat_id = ?",
            (bot_name, str(chat_id)),
        )
        conn.commit()
        conn.close()


def was_alert_sent(bot_name: str, chat_id: str, source: str, external_id: str, watch_id: Optional[int]) -> bool:
    with db_lock:
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT id FROM sent_alerts
            WHERE bot_name = ? AND chat_id = ? AND source = ? AND external_id = ? AND COALESCE(watch_id, -1) = COALESCE(?, -1)
            LIMIT 1
            """,
            (bot_name, str(chat_id), source, external_id, watch_id),
        ).fetchone()
        conn.close()
    return row is not None


def mark_alert_sent(bot_name: str, chat_id: str, source: str, external_id: str, watch_id: Optional[int]):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO sent_alerts (bot_name, chat_id, source, external_id, watch_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (bot_name, str(chat_id), source, external_id, watch_id),
        )
        conn.commit()
        conn.close()


def get_recent_alerts(bot_name: str, chat_id: str, limit: int = 20):
    with db_lock:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT source, external_id, watch_id, created_at
            FROM sent_alerts
            WHERE bot_name = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (bot_name, str(chat_id), limit),
        ).fetchall()
        conn.close()
    return rows


def clear_alerts(bot_name: str, chat_id: str):
    with db_lock:
        conn = get_db_connection()
        conn.execute(
            "DELETE FROM sent_alerts WHERE bot_name = ? AND chat_id = ?",
            (bot_name, str(chat_id)),
        )
        conn.commit()
        conn.close()


def build_opportunity_line(item: dict, bot_name: str, chat_id: str) -> dict:
    title = item.get("title", "Untitled")
    price, currency = parse_price(item)
    external_id = extract_external_id(item)
    url = extract_item_url(item)

    est_value, est_profit, score, notes = estimate_flip_score(title, price)

    save_opportunity(
        bot_name=bot_name,
        chat_id=chat_id,
        source="ebay",
        external_id=external_id,
        title=title,
        price=price,
        est_value=est_value,
        est_profit=est_profit,
        score=score,
        currency=currency,
        url=url,
        notes=notes,
    )

    return {
        "external_id": external_id,
        "title": title,
        "price": price,
        "currency": currency,
        "est_value": est_value,
        "est_profit": est_profit,
        "score": score,
        "url": url,
        "notes": notes,
    }


def format_opportunities(opps: List[dict]) -> str:
    if not opps:
        return "No opportunities found."

    parts = []
    for i, o in enumerate(opps, start=1):
        parts.append(
            f"{i}. {o['title']}\n"
            f"Price: {o['price']} {o['currency'] or ''}\n"
            f"Est. value: {o['est_value']}\n"
            f"Est. profit: {o['est_profit']}\n"
            f"Score: {o['score']}\n"
            f"Notes: {o['notes']}\n"
            f"URL: {o['url'] or 'n/a'}"
        )
    return "\n\n".join(parts)


async def run_watch_scans_for_chat(bot: BotConfig, bot_name: str, chat_id: str) -> List[str]:
    results = []
    watches = get_watches(bot_name, chat_id)

    for watch in watches:
        source = watch["source"]
        query_text = watch["query_text"]
        min_profit = safe_float(watch["min_profit"]) or 0
        max_buy = safe_float(watch["max_buy"])
        min_score = safe_float(watch["min_score"]) or 0
        email_on = bool(watch["email_on"])
        watch_id = watch["id"]

        if source == "ebay":
            try:
                items = search_ebay_items(query_text, limit=20)
            except Exception as e:
                results.append(f"Watch {watch_id} ({query_text}) failed: {str(e)}")
                continue

            for item in items:
                opp = build_opportunity_line(item, bot_name, chat_id)

                if opp["price"] is None or opp["est_profit"] is None or opp["score"] is None:
                    continue
                if opp["est_profit"] < min_profit:
                    continue
                if max_buy is not None and opp["price"] > max_buy:
                    continue
                if opp["score"] < min_score:
                    continue
                if was_alert_sent(bot_name, chat_id, "ebay", opp["external_id"], watch_id):
                    continue

                msg = (
                    f"🚨 Opportunity Alert\n\n"
                    f"Source: eBay\n"
                    f"Watch: {query_text}\n"
                    f"Title: {opp['title']}\n"
                    f"Price: {opp['price']} {opp['currency'] or ''}\n"
                    f"Est. value: {opp['est_value']}\n"
                    f"Est. profit: {opp['est_profit']}\n"
                    f"Score: {opp['score']}\n"
                    f"URL: {opp['url'] or 'n/a'}\n"
                    f"Notes: {opp['notes']}"
                )

                await send_message(bot.token, int(chat_id), msg)

                if email_on:
                    send_email_alert(
                        subject=f"Opportunity Alert: {opp['title'][:80]}",
                        body=msg
                    )

                mark_alert_sent(bot_name, chat_id, "ebay", opp["external_id"], watch_id)
                results.append(f"Alert sent for watch {watch_id}: {opp['title'][:80]}")

        elif source == "catawiki":
            # Intentional manual/watchlist mode only until a compliant automated integration path is verified
            results.append(f"Watch {watch_id} is stored in manual Catawiki mode: {query_text}")

        else:
            results.append(f"Watch {watch_id} skipped: unsupported source {source}")

    return results

# =========================================================
# COMMAND HANDLERS
# =========================================================

async def handle_common_commands(bot: BotConfig, chat_id: int, text: str, bot_name: str) -> bool:
    lowered = text.strip()

    if lowered.startswith("/remember "):
        memory_text = lowered[len("/remember "):].strip()
        if not memory_text:
            await send_message(bot.token, chat_id, "Usage: /remember <text>")
            return True
        add_memory(bot_name, str(chat_id), memory_text)
        await send_message(bot.token, chat_id, f"Saved memory:\n- {memory_text}")
        return True

    if lowered == "/memories":
        memories = get_memories(bot_name, str(chat_id), limit=50)
        if not memories:
            await send_message(bot.token, chat_id, "No saved memories yet.")
            return True
        formatted = "\n".join([f"{i+1}. {m}" for i, m in enumerate(memories)])
        await send_message(bot.token, chat_id, f"Saved memories:\n\n{formatted}")
        return True

    if lowered == "/reset":
        clear_messages(bot_name, str(chat_id))
        await send_message(bot.token, chat_id, "Conversation history for this bot/chat has been cleared.")
        return True

    if lowered == "/forgetall":
        clear_memories(bot_name, str(chat_id))
        await send_message(bot.token, chat_id, "Saved durable memories for this bot/chat have been cleared.")
        return True

    if lowered == "/connectors":
        status = get_connector_status()
        msg = "Connector status:\n\n" + "\n".join([f"- {k}: {v}" for k, v in status.items()])
        await send_message(bot.token, chat_id, msg)
        return True

    return False


async def handle_project_commands(bot: BotConfig, chat_id: int, text: str, bot_name: str) -> bool:
    lowered = text.strip()

    if lowered.startswith("/ebay "):
        query = lowered[len("/ebay "):].strip()
        if not query:
            await send_message(bot.token, chat_id, "Usage: /ebay <keywords>")
            return True
        try:
            await send_chat_action(bot.token, chat_id, "typing")
            items = search_ebay_items(query, limit=10)
            opps = [build_opportunity_line(item, bot_name, str(chat_id)) for item in items[:5]]
            await send_message(bot.token, chat_id, f"eBay scan for: {query}\n\n{format_opportunities(opps)}")
        except Exception as e:
            await send_message(bot.token, chat_id, f"eBay scan failed: {str(e)}")
        return True

    if lowered.startswith("/scan "):
        query = lowered[len("/scan "):].strip()
        if not query:
            await send_message(bot.token, chat_id, "Usage: /scan <keywords>")
            return True
        try:
            await send_chat_action(bot.token, chat_id, "typing")
            items = search_ebay_items(query, limit=10)
            opps = [build_opportunity_line(item, bot_name, str(chat_id)) for item in items[:5]]
            intro = (
                f"Opportunity scan for: {query}\n\n"
                f"Automated source currently active: eBay official API.\n"
                f"Catawiki is kept in manual/watchlist mode until a compliant automated integration path is confirmed.\n\n"
            )
            await send_message(bot.token, chat_id, intro + format_opportunities(opps))
        except Exception as e:
            await send_message(bot.token, chat_id, f"Opportunity scan failed: {str(e)}")
        return True

    if lowered.startswith("/watch "):
        remainder = lowered[len("/watch "):].strip()

        if remainder.startswith("ebay "):
            payload = remainder[len("ebay "):].strip()
            kv = parse_key_values(payload)
            query = strip_key_values(payload)

            min_profit = safe_float(kv.get("min_profit")) or 0
            max_buy = safe_float(kv.get("max_buy"))
            min_score = safe_float(kv.get("min_score")) or 0
            email_on = parse_bool(kv.get("email", "off"))

            if not query:
                await send_message(
                    bot.token,
                    chat_id,
                    'Usage: /watch ebay <keywords> min_profit=50 max_buy=200 min_score=15 email=on'
                )
                return True

            add_watch(
                bot_name=bot_name,
                chat_id=str(chat_id),
                source="ebay",
                query_text=query,
                min_profit=min_profit,
                max_buy=max_buy,
                min_score=min_score,
                email_on=email_on,
                notes="user-defined eBay watch",
            )

            await send_message(
                bot.token,
                chat_id,
                f"Saved eBay watch:\n"
                f"Query: {query}\n"
                f"min_profit={min_profit}\n"
                f"max_buy={max_buy}\n"
                f"min_score={min_score}\n"
                f"email={'on' if email_on else 'off'}"
            )
            return True

        if remainder.startswith("catawiki "):
            payload = remainder[len("catawiki "):].strip()
            kv = parse_key_values(payload)
            query = strip_key_values(payload)

            min_profit = safe_float(kv.get("min_profit")) or 0
            min_score = safe_float(kv.get("min_score")) or 0
            email_on = parse_bool(kv.get("email", "off"))

            if not query:
                await send_message(
                    bot.token,
                    chat_id,
                    'Usage: /watch catawiki <notes_or_url> min_profit=50 min_score=15 email=off'
                )
                return True

            add_watch(
                bot_name=bot_name,
                chat_id=str(chat_id),
                source="catawiki",
                query_text=query,
                min_profit=min_profit,
                max_buy=None,
                min_score=min_score,
                email_on=email_on,
                notes="manual Catawiki watch",
            )

            await send_message(
                bot.token,
                chat_id,
                "Saved Catawiki watch in manual mode.\n"
                "It will be stored and listed, but not auto-scraped until a compliant integration path is confirmed."
            )
            return True

        await send_message(
            bot.token,
            chat_id,
            "Usage:\n"
            "/watch ebay <keywords> min_profit=50 max_buy=200 min_score=15 email=on\n"
            "/watch catawiki <notes_or_url> min_profit=50 min_score=15 email=off"
        )
        return True

    if lowered == "/watches":
        watches = get_watches(bot_name, str(chat_id))
        if not watches:
            await send_message(bot.token, chat_id, "No active watches.")
            return True

        lines = []
        for w in watches:
            lines.append(
                f"{w['id']}. [{w['source']}] {w['query_text']}\n"
                f"min_profit={w['min_profit']} | max_buy={w['max_buy']} | min_score={w['min_score']} | email={'on' if w['email_on'] else 'off'}"
            )
        await send_message(bot.token, chat_id, "Active watches:\n\n" + "\n\n".join(lines))
        return True

    if lowered == "/clearwatches":
        clear_watches(bot_name, str(chat_id))
        await send_message(bot.token, chat_id, "All watches cleared for this bot/chat.")
        return True

    if lowered == "/alerts":
        alerts = get_recent_alerts(bot_name, str(chat_id), limit=20)
        if not alerts:
            await send_message(bot.token, chat_id, "No recent alerts.")
            return True

        out = []
        for i, a in enumerate(alerts, start=1):
            out.append(
                f"{i}. source={a['source']} | external_id={a['external_id']} | watch_id={a['watch_id']} | at={a['created_at']}"
            )
        await send_message(bot.token, chat_id, "Recent alerts:\n\n" + "\n".join(out))
        return True

    if lowered == "/clearalerts":
        clear_alerts(bot_name, str(chat_id))
        await send_message(bot.token, chat_id, "Alert history cleared for this bot/chat.")
        return True

    if lowered == "/opps":
        rows = get_recent_opportunities(bot_name, str(chat_id), limit=10)
        if not rows:
            await send_message(bot.token, chat_id, "No stored opportunities yet.")
            return True

        out = []
        for i, row in enumerate(rows, start=1):
            out.append(
                f"{i}. [{row['source']}] {row['title']}\n"
                f"Price: {row['price']} {row['currency'] or ''}\n"
                f"Est. value: {row['est_value']}\n"
                f"Est. profit: {row['est_profit']}\n"
                f"Score: {row['score']}\n"
                f"URL: {row['url'] or 'n/a'}"
            )
        await send_message(bot.token, chat_id, "Recent opportunities:\n\n" + "\n\n".join(out))
        return True

    if lowered == "/runscan":
        results = await run_watch_scans_for_chat(bot, bot_name, str(chat_id))
        msg = "Manual watch scan completed.\n\n" + ("\n".join(results) if results else "No matching alerts.")
        await send_message(bot.token, chat_id, msg)
        return True

    return False


async def handle_command(bot: BotConfig, chat_id: int, text: str, bot_name: str) -> bool:
    common_handled = await handle_common_commands(bot, chat_id, text, bot_name)
    if common_handled:
        return True

    if bot_name == "project":
        return await handle_project_commands(bot, chat_id, text, bot_name)

    return False

# =========================================================
# ROUTES
# =========================================================

@app.get("/")
async def healthcheck():
    bots = get_bot_configs()
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "bots": list(bots.keys()),
        "connectors": get_connector_status(),
    }


@app.post("/internal/run-scans")
async def internal_run_scans(request: Request):
    secret = request.headers.get("X-Internal-Secret") or request.query_params.get("secret")
    if secret != INTERNAL_SCAN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    bots = get_bot_configs()
    summary = []

    for bot_name, bot in bots.items():
        if bot_name != "project":
            continue

        with db_lock:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT DISTINCT chat_id
                FROM watches
                WHERE bot_name = ? AND active = 1
                """,
                (bot_name,),
            ).fetchall()
            conn.close()

        for row in rows:
            chat_id = row["chat_id"]
            results = await run_watch_scans_for_chat(bot, bot_name, chat_id)
            summary.append({"chat_id": chat_id, "results": results})

    return {"status": "ok", "summary": summary}


async def process_message(req: Request, bot_name: str):
    bot = get_bot(bot_name)
    if not bot:
        return {"status": "error", "message": f"Bot '{bot_name}' is not configured"}

    data = await req.json()

    if "message" not in data:
        return {"status": "ignored"}

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        await send_message(bot.token, chat_id, "Please send me a text message.")
        return {"status": "ok"}

    handled = await handle_command(bot, chat_id, text, bot_name)
    if handled:
        return {"status": "ok"}

    try:
        add_message(bot_name, str(chat_id), "user", text)
        await send_chat_action(bot.token, chat_id, "typing")
        answer = generate_answer(bot_name, str(chat_id), bot.prompt, text)
        add_message(bot_name, str(chat_id), "assistant", answer)
        await send_message(bot.token, chat_id, answer)
    except Exception as e:
        await send_message(bot.token, chat_id, f"Error while generating the response: {str(e)}")

    return {"status": "ok"}


@app.post("/webhook/main")
async def telegram_webhook_main(req: Request):
    return await process_message(req, "main")


@app.post("/webhook/project")
async def telegram_webhook_project(req: Request):
    return await process_message(req, "project")
