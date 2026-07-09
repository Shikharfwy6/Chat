import logging
import os
import asyncio
from flask import Flask, request
from telegram import Update, Bot
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

# Direct Telegram Bot Client
bot = Bot(token=BOT_TOKEN)

async def process_telegram_update(update_json):
    """Sare incoming messages aur channel replies ko direct handle karne ke liye"""
    
    # 1. USER SE BOT PAR MESSAGE AANA (Private Chat)
    if "message" in update_json and update_json["message"]["chat"]["type"] == "private":
        msg = update_json["message"]
        user_id = msg["from"]["id"]
        first_name = msg["from"].get("first_name", "User")
        
        # User ka mention HTML format mein
        user_mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
        caption_text = f"📩 **New Message from {user_mention}**:\n👤 UserID: `{user_id}`"
        
        sent_msg = None
        try:
            if "photo" in msg:
                file_id = msg["photo"][-1]["file_id"]  # Best quality photo
                user_caption = f"\n\n📝 Caption: {msg['caption']}" if "caption" in msg else ""
                sent_msg = await bot.send_photo(
                    chat_id=CHANNEL_ID, photo=file_id, caption=caption_text + user_caption, parse_mode="HTML"
                )
            elif "text" in msg:
                text_to_send = f"{caption_text}\n\n💬 Message:\n{msg['text']}"
                sent_msg = await bot.send_message(chat_id=CHANNEL_ID, text=text_to_send, parse_mode="HTML")
            
            # MongoDB mein record save karna
            if sent_msg:
                messages_col.insert_one({"channel_msg_id": sent_msg.message_id, "user_id": user_id})
                print(f"✅ Stored in DB: Channel Msg {sent_msg.message_id} -> User {user_id}")
        except Exception as e:
            print(f"Error forwarding to channel: {e}")

    # 2. CHANNEL MEIN RE-PLY KARNA (Channel Post)
    elif "channel_post" in update_json:
        post = update_json["channel_post"]
        
        # Check karein ki kya ye kisi post ka reply hai
        if "reply_to_message" in post:
            reply_to_msg_id = post["reply_to_message"]["message_id"]
            
            # DB se check karein ki ye kis user ka message tha
            record = messages_col.find_one({"channel_msg_id": reply_to_msg_id})
            
            if record:
                user_id = record["user_id"]
                try:
                    if "photo" in post:
                        file_id = post["photo"][-1]["file_id"]
                        admin_caption = f"💬 **Admin Reply:**\n\n{post['caption']}" if "caption" in post else "💬 **Admin Reply (Photo)**"
                        await bot.send_photo(chat_id=user_id, photo=file_id, caption=admin_caption, parse_mode="HTML")
                    elif "text" in post:
                        await bot.send_message(chat_id=user_id, text=f"💬 **Admin Reply:**\n\n{post['text']}", parse_mode="HTML")
                    print(f"✅ Reply sent to user: {user_id}")
                except Exception as e:
                    print(f"Error sending reply to user: {e}")
            else:
                print(f"⚠️ Memory/DB mein is message ID ({reply_to_msg_id}) ki entry nahi mili.")

# --- FLASK ROUTES ---

@app.route('/')
def home():
    return "Bot is running 24/7 with raw webhook processor on Vercel!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update_json = request.get_json(force=True)
            
            # Async function ko chalane ke liye loop setup
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_telegram_update(update_json))
            loop.close()
        except Exception as e:
            print(f"Webhook Error: {e}")
    return "OK", 200

@app.route('/setup')
def setup():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    url_to_use = VERCEL_URL if VERCEL_URL else f"https://{os.environ.get('VERCEL_PROJECT_PRODUCTION_URL')}"
    webhook_url = f"{url_to_use}/webhook"
    
    # Telegram ko explicitly batana ki message aur channel_post dono bhejni hain
    success = loop.run_until_complete(bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message", "channel_post"]
    ))
    loop.close()
    
    if success:
        return f"✅ Webhook successfully set to {webhook_url}"
    return "❌ Failed to set webhook"

if __name__ == '__main__':
    app.run(debug=True)
