import os
import requests
from fastapi import FastAPI, Request
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

SYSTEM_PROMPT = """
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
- Constantly look for legitimate opportunities for business creation, arbitrage, automation, services, media, products, research, distribution, sales, and asymmetric upside.
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


async def send_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    if not text:
        text = "I could not generate a response."

    max_length = 4000
    chunks = [text[i:i + max_length] for i in range(0, len(text), max_length)]

    for chunk in chunks:
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk
            },
            timeout=30
        )


@app.get("/")
async def healthcheck():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()

    if "message" not in data:
        return {"status": "ignored"}

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        await send_message(chat_id, "Please send me a text message.")
        return {"status": "ok"}

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        )

        answer = response.output_text.strip()
        await send_message(chat_id, answer)

    except Exception as e:
        await send_message(
            chat_id,
            f"Error while generating the response: {str(e)}"
        )

    return {"status": "ok"}
