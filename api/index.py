import logging
import os
import requests
from flask import Flask, request
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

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_request(method, data):
    """Telegram API ko direct request bhejne ke liye helper function"""
    url = f"{TELEGRAM_API_URL}/{method}"
    try:
        response = requests.post(url, json=data)
        return response.json()
    except Exception as e:
        print(f"Error sending request to Telegram: {e}")
        return None

# --- FLASK ROUTES ---

@app.route('/')
def home():
    return "Bot is running 24/7 safely with Requests on Vercel!"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            update_json = request.get_json(force=True)
            
            # 1. USER SE BOT PAR MESSAGE AANA (Private Chat)
            if "message" in update_json and update_json["message"]["chat"]["type"] == "private":
                msg = update_json["message"]
                user_id = msg["from"]["id"]
                first_name = msg["from"].get("first_name", "User")
                
                user_mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
                caption_text = f"📩 **New Message from {user_mention}**:\n👤 UserID: `{user_id}`"
                
                res = None
                # Agar photo bheji hai
                if "photo" in msg:
                    file_id = msg["photo"][-1]["file_id"]
                    user_caption = f"\n\n📝 Caption: {msg['caption']}" if "caption" in msg else ""
                    res = send_telegram_request("sendPhoto", {
                        "chat_id": CHANNEL_ID,
                        "photo": file_id,
                        "caption": caption_text + user_caption,
                        "parse_mode": "HTML"
                    })
                # Agar text bheja hai
                elif "text" in msg:
                    text_to_send = f"{caption_text}\n\n💬 Message:\n{msg['text']}"
                    res = send_telegram_request("sendMessage", {
                        "chat_id": CHANNEL_ID,
                        "text": text_to_send,
                        "parse_mode": "HTML"
                    })
                
                # MongoDB mein save karein
                if res and res.get("ok"):
                    channel_msg_id = res["result"]["message_id"]
                    messages_col.insert_one({"channel_msg_id": channel_msg_id, "user_id": user_id})
                    print(f"✅ Stored in DB: Channel Msg {channel_msg_id} -> User {user_id}")

            # 2. CHANNEL MEIN REPLY KARNA (Channel Post)
            elif "channel_post" in update_json:
                post = update_json["channel_post"]
                
                if "reply_to_message" in post:
                    reply_to_msg_id = post["reply_to_message"]["message_id"]
                    
                    # DB se User ID nikalna
                    record = messages_col.find_one({"channel_msg_id": reply_to_msg_id})
                    
                    if record:
                        user_id = record["user_id"]
                        if "photo" in post:
                            file_id = post["photo"][-1]["file_id"]
                            admin_caption = f"💬 **Admin Reply:**\n\n{post['caption']}" if "caption" in post else "💬 **Admin Reply (Photo)**"
                            send_telegram_request("sendPhoto", {
                                "chat_id": user_id,
                                "photo": file_id,
                                "caption": admin_caption,
                                "parse_mode": "HTML"
                            })
                        elif "text" in post:
                            send_telegram_request("sendMessage", {
                                "chat_id": user_id,
                                "text": f"💬 **Admin Reply:**\n\n{post['text']}",
                                "parse_mode": "HTML"
                            })
                        print(f"✅ Reply sent to user: {user_id}")
                    else:
                        print(f"⚠️ DB mein is message ID ({reply_to_msg_id}) ki entry nahi mili.")
                        
        except Exception as e:
            print(f"Webhook Processing Error: {e}")
            
    return "OK", 200

@app.route('/setup')
def setup():
    url_to_use = VERCEL_URL if VERCEL_URL else f"https://{os.environ.get('VERCEL_PROJECT_PRODUCTION_URL')}"
    webhook_url = f"{url_to_use}/webhook"
    
    # Webhook set karne ke liye direct API hit karna
    res = send_telegram_request("setWebhook", {
        "url": webhook_url,
        "allowed_updates": ["message", "channel_post"]
    })
    
    if res and res.get("ok"):
        return f"✅ Webhook successfully set to {webhook_url}"
    return f"❌ Failed to set webhook: {res}"

if __name__ == '__main__':
    app.run(debug=True)
