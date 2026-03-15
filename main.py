import os
import requests
from fastapi import FastAPI, Request
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# --- Bot tokens ---
TELEGRAM_TOKEN_MAIN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_TOKEN_2 = os.environ.get("TELEGRAM_TOKEN_2")

# --- Bot prompts ---
SYSTEM_PROMPT_MAIN = """
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

SYSTEM_PROMPT_2 = """
You are the user's second elite AI agent for a separate project.

Your job:
- Focus deeply on the user's second project.
- Keep this project separate from the main bot.
- Be highly strategic, practical, structured, and action-oriented.
- Help the user think more clearly, move faster, and execute better.
- Suggest concrete next steps and useful prioritization.
- Act like a top-tier operator, not a generic chatbot.

Rules:
- Be sharp, concise, and useful.
- Structure answers clearly when it helps.
- Prioritize practical actions over vague ideas.
- If something is uncertain, say so clearly.
- Always try to increase leverage, clarity, speed, and quality.
""".strip()


def chunk_text(text: str, max_length: int = 4000):
    if not text:
        return ["I could not generate a response."]
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


async def send_message(token: str, chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for chunk in chunk_text(text):
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk
            },
            timeout=30
        )


def generate_answer(system_prompt: str, user_text: str) -> str:
    response = client.responses.create(
        model="gpt-4.1-mini",
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
    return response.output_text.strip()


async def process_telegram_message(req: Request, token: str, system_prompt: str):
    data = await req.json()

    if "message" not in data:
        return {"status": "ignored"}

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        await send_message(token, chat_id, "Please send me a text message.")
        return {"status": "ok"}

    try:
        answer = generate_answer(system_prompt, text)
        await send_message(token, chat_id, answer)
    except Exception as e:
        await send_message(token, chat_id, f"Error while generating the response: {str(e)}")

    return {"status": "ok"}


@app.get("/")
async def healthcheck():
    return {
        "status": "ok",
        "bots": {
            "main": bool(TELEGRAM_TOKEN_MAIN),
            "bot2": bool(TELEGRAM_TOKEN_2)
        }
    }


@app.post("/webhook/main")
async def telegram_webhook_main(req: Request):
    return await process_telegram_message(
        req=req,
        token=TELEGRAM_TOKEN_MAIN,
        system_prompt=SYSTEM_PROMPT_MAIN
    )


@app.post("/webhook/project")
async def telegram_webhook_project(req: Request):
    if not TELEGRAM_TOKEN_2:
        return {"status": "error", "message": "TELEGRAM_TOKEN_2 is not configured"}

    return await process_telegram_message(
        req=req,
        token=TELEGRAM_TOKEN_2,
        system_prompt=SYSTEM_PROMPT_2
    )
