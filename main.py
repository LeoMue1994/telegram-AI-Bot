import os
import requests
from fastapi import FastAPI, Request
from openai import OpenAI

app = FastAPI()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

async def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

@app.post("/")
async def telegram_webhook(req: Request):
    data = await req.json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"You are a helpful personal AI assistant.\nUser: {text}"
        )

        answer = response.output_text

        await send_message(chat_id, answer)

    return {"status": "ok"}
