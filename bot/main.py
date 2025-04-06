import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import CallbackContext

import logging

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
	raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

# Telegram app
app_bot = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, Noam!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("echo", echo))

# FastAPI app
app = FastAPI()

@app.post("/webhook")
async def telegram_webhook(req: Request):
	update = Update.de_json(await req.json(), app_bot.bot)
	await app_bot.process_update(update)
	return {"ok": True}
