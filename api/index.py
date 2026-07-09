import logging
import re
import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from pymongo import MongoClient

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
MONGO_URI = os.environ.get("MONGO_URI")
VERCEL_URL = os.environ.get("VERCEL_URL")
# ---------------------

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)

# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client['telegram_forward_bot']
messages_col = db['messages']

# Telegram Application Setup
application = Application.builder().token(BOT_TOKEN).build()

# Global flag initialization ko track karne ke liye
APP_INITIALIZED = False

async def init_application():
    """Application ko safely initialize aur start karne ke liye"""
    global APP_INITIALIZED
    if not APP_INITIALIZED:
        await application.initialize()
        await application.start()
        APP_INITIALIZED = True

async def handle_incoming_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == CHANNEL_ID:
        return

    user = update.effective_user
    msg = update.message
    caption_text = f"📩 **New Message from {user.mention_html()}**:\n👤 UserID: `{user.id}`"
    sent_message = None

    try:
        if msg.photo:
            file_id = msg.photo[-1].file_id
            user_caption = f"\n\n📝 Caption: {msg.caption}" if msg.caption else ""
            sent_message = await context.bot.send_photo(
                chat_id=CHANNEL_ID, photo=file_id, caption=caption_text + user_caption, parse_mode="HTML"
            )
        elif msg.text:
            sent_message = await context.bot.send_message(
                chat_id=CHANNEL_ID, text=f"{caption_text}\n\n💬 Message:\n{msg.text}", parse_mode="HTML"
            )

        if sent_message:
            messages_col.insert_one({"channel_msg_id": sent_message.message_id, "user_id": user.id})
    except Exception as e:
        print(f"Error forwarding: {e}")

async def handle_channel_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post if update.channel_post else update.message
    if not msg or not msg.reply_to_message:
        return

    reply_to_msg = msg.reply_to_message
    record = messages_col.find_one({"channel_msg_id": reply_to_msg.message_id})

    if record:
        user_id = record["user_id"]
        try:
            if msg.photo:
                file_id = msg.photo[-1].file_id
                admin_caption = f"💬 **Admin Reply:**\n\n{msg.caption}" if msg.caption else "💬 **Admin Reply (Photo)**"
                await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=admin_caption, parse_mode="HTML")
            elif msg.text:
                await context.bot.send_message(chat_id=user_id, text=f"💬 **Admin Reply:**\n\n{msg.text}", parse_mode="HTML")
        except Exception as e:
            print(f"Error replying: {e}")

# Handlers
application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.PHOTO), handle_incoming_messages))
application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST & (filters.TEXT | filters.PHOTO), handle_channel_replies))

# --- FLASK ROUTES ---

@app.route('/')
def home():
    return "Bot is running 24/7 on Vercel with fix!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # [FIXED] Custom function se safely initialize karein
            loop.run_until_complete(init_application())
            loop.run_until_complete(application.process_update(update))
            loop.close()
        except Exception as e:
            print(f"Webhook Error: {e}")
    return "OK", 200

@app.route('/setup')
def setup():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.run_until_complete(init_application())
        
    url_to_use = VERCEL_URL if VERCEL_URL else f"https://{os.environ.get('VERCEL_PROJECT_PRODUCTION_URL')}"
    webhook_url = f"{url_to_use}/webhook"
    
    success = loop.run_until_complete(application.bot.set_webhook(url=webhook_url))
    loop.close()
    if success:
        return f"✅ Webhook successfully set to {webhook_url}"
    return "❌ Failed to set webhook"

if __name__ == '__main__':
    app.run(debug=True)
