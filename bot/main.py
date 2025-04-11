import os
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import CallbackContext

# Configure logging
logging.basicConfig(
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "false").lower() == "true"

if not TOKEN:
	raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

# Telegram app
app_bot = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	logging.info(f"Start command received from user {update.effective_user.id}")
	await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello, Noam!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
	logging.info(f"Echo command received from user {update.effective_user.id}: {update.message.text}")
	await context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("echo", echo))

# FastAPI app
app = FastAPI()

@app.get("/")
async def root():
	return {"status": "ok", "mode": "webhook" if WEBHOOK_MODE else "polling"}

@app.get("/health")
async def health_check():
	return {"status": "healthy"}

@app.post("/webhook")
async def telegram_webhook(req: Request):
	try:
		update = Update.de_json(await req.json(), app_bot.bot)
		logging.info(f"Webhook update received: {update}")
		await app_bot.process_update(update)
		return {"ok": True}
	except Exception as e:
		logging.error(f"Error processing webhook update: {e}")
		raise

if __name__ == "__main__":
	print(f"WEBHOOK_MODE: {WEBHOOK_MODE}")
	if WEBHOOK_MODE:
		# In webhook mode, FastAPI will handle the updates
		import uvicorn
		uvicorn.run(app, host="0.0.0.0", port=8000)
	else:
		# In polling mode, run the bot directly
		app_bot.run_polling()