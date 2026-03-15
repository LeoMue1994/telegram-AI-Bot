import os
import requests
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from openai import OpenAI

app = FastAPI()

# =========================
# CONFIG
# =========================

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_TOKEN_2 = os.environ.get("TELEGRAM_TOKEN_2")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# PROMPTS
# =========================

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
- Do not suggest scams, deception, spam, market manipulation, illegal actions, or unethical behavior.

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

Default response structure when useful:
1. Best answer
2. Why it matters
3. Best next steps

Your standard should be exceptional usefulness.
""".strip()

PROJECT_BOT_PROMPT = """
You are the user's second elite AI agent for a separate project.

Mission:
Help the user build, improve, and execute this specific project with exceptional clarity and leverage.

Operating style:
- Think like a top-tier operator and strategist.
- Be highly practical, structured, and action-oriented.
- Focus on execution, prioritization, speed, and quality.
- Keep this bot's project context separate from the user's other bots and projects.

What to optimize for:
- Clarity
- Momentum
- Better decisions
- High-leverage actions
- Competitive advantage
- Strong execution

Rules:
- Be concise, sharp, and useful.
- Structure answers when helpful.
- Turn messy ideas into clear actions.
- If something is uncertain, say so.
- Prefer concrete next steps over abstract discussion.
""".strip()

# =========================
# BOT CONFIG
# =========================

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

# =========================
# HELPERS
# =========================

def chunk_text(text: str, max_length: int = 4000) -> List[str]:
    if not text:
        return ["I could not generate a response."]
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


async def send_message(token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for chunk in chunk_text(text):
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
            },
            timeout=30,
        )


def generate_answer(system_prompt: str, user_text: str) -> str:
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    text = getattr(response, "output_text", None)
    if text:
        return text.strip()

    return "I could not generate a response."

# =========================
# ROUTES
# =========================

@app.get("/")
async def healthcheck():
    bots = get_bot_configs()
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "bots": list(bots.keys())
    }


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

    try:
        answer = generate_answer(bot.prompt, text)
        await send_message(bot.token, chat_id, answer)
    except Exception as e:
        await send_message(
            bot.token,
            chat_id,
            f"Error while generating the response: {str(e)}"
        )

    return {"status": "ok"}


@app.post("/webhook/main")
async def telegram_webhook_main(req: Request):
    return await process_message(req, "main")


@app.post("/webhook/project")
async def telegram_webhook_project(req: Request):
    return await process_message(req, "project")
