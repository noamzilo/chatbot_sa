import os
import logging
import requests
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.ext import CallbackContext
from telegram.ext import MessageHandler, filters

# Configure logging
logging.basicConfig(
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "false").lower() == "true"
RAG_API_URL = "http://rag_api:8000"  # Using Docker service name

if not TOKEN:
	raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

# Telegram app
app_bot = ApplicationBuilder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	logging.info(f"Start command received from user {update.effective_user.id}")
	await context.bot.send_message(
		chat_id=update.effective_chat.id,
		text="Hello! I'm your RAG-powered chatbot. Ask me anything and I'll search through our knowledge base to find relevant information."
	)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
	try:
		query = update.message.text
		logging.info(f"Query received from user {update.effective_user.id}: {query}")
		
		# Query the RAG API
		response = requests.post(
			f"{RAG_API_URL}/query",
			json={"query": query, "limit": 3}
		)
		response.raise_for_status()
		results = response.json()
		
		if not results:
			await update.message.reply_text(
				"I couldn't find any relevant information in our knowledge base. "
				"Please try rephrasing your question."
			)
			return
			
		# Format the response
		message = "Here's what I found:\n\n"
		for i, doc in enumerate(results, 1):
			message += f"{i}. {doc['title'] or 'Untitled'}\n"
			message += f"   {doc['content'][:200]}...\n"
			message += f"   Source: {doc['url']}\n\n"
			
		await update.message.reply_text(message)
		
	except requests.exceptions.RequestException as e:
		logging.error(f"Error querying RAG API: {e}")
		await update.message.reply_text(
			"Sorry, I'm having trouble accessing our knowledge base right now. "
			"Please try again later."
		)
	except Exception as e:
		logging.error(f"Error processing message: {e}")
		await update.message.reply_text(
			"Sorry, something went wrong. Please try again later."
		)

# This catches any text that is NOT a /command
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

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