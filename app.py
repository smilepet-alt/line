import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import google.generativeai as genai

# 從雲端環境讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# 你的個人 LINE User ID (稍後我們要設定在環境變數裡)
MY_LINE_USER_ID = os.environ.get("MY_LINE_USER_ID")

app = Flask(__name__)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.8-flash')

# 1. 原本的被動回覆功能
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
    try:
        response = model.generate_content(user_message)
        reply_text = response.text
    except Exception as e:
        reply_text = f"發生錯誤了：{str(e)}"

    with ApiClient(configuration) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# 2. 新增的主動推播提醒功能 (給定時工具呼叫用的網址)
@app.route("/push-reminder", methods=['GET'])
def push_reminder():
    if not MY_LINE_USER_ID:
        return "尚未設定 MY_LINE_USER_ID", 400
    
    # 讓 AI 幫忙生成一句溫馨的早安與行程提醒打氣話語
    try:
        ai_prompt = "請幫我寫一句簡短、溫馨且充滿活力的早安問候，並提醒今天要注意開會與重要行程。"
        ai_response = model.generate_content(ai_prompt)
        reminder_text = ai_response.text
    except Exception:
        reminder_text = "早安！記得今天有會議與重要行程要忙，祝你有個順利的一天！"

    # 主動發送訊息到你的 LINE
    with ApiClient(configuration) as api_client:
        line_api = MessagingApi(api_client)
        line_api.push_message(
            PushMessageRequest(
                to=MY_LINE_USER_ID,
                messages=[TextMessage(text=reminder_text)]
            )
        )
    return "推播成功！"

if __name__ == "__main__":
    app.run(port=5000)
