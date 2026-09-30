import os
import json
from datetime import datetime
import pytz
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

app = Flask(__name__)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.6-flash')

# 建立 Google 日曆服務物件
def get_calendar_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    return build('calendar', 'v3', credentials=credentials)

# 新增行程到 Google 日曆
def add_calendar_event(summary, start_time_iso, end_time_iso):
    service = get_calendar_service()
    if not service or not GOOGLE_CALENDAR_ID:
        return False, "日曆環境變數未完整設定"
    
    event = {
        'summary': summary,
        'start': {'dateTime': start_time_iso, 'timeZone': 'Asia/Taipei'},
        'end': {'dateTime': end_time_iso, 'timeZone': 'Asia/Taipei'},
    }
    created_event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
    return True, created_event.get('htmlLink')

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
    # 取得台北目前時間供 AI 計算相對時間（例如「明天」、「下週一」）
    tz = pytz.timezone('Asia/Taipei')
    now_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M (%A)')

    prompt = f"""
你是一個智慧助理。當前台北時間是：{now_str}。
使用者說：「{user_message}」

請判斷這段話是否包含「新增行程、提醒或開會」的意圖：
1. 如果是，請嚴格按照以下 JSON 格式回傳，不要加上任何 Markdown 標記或多餘文字：
{{"action": "create_event", "summary": "事件名稱", "start": "YYYY-MM-DDTHH:MM:SS+08:00", "end": "YYYY-MM-DDTHH:MM:SS+08:00"}}
（如果沒有說明持續時間，結束時間預設為開始時間加 1 小時）

2. 如果只是普通聊天或問題，請直接用親切自然的繁體中文回覆即可。
"""
    try:
        response = model.generate_content(prompt)
        res_text = response.text.strip()

        # 判斷是否為預約行程的 JSON
        if res_text.startswith("{") and res_text.endswith("}"):
            event_data = json.loads(res_text)
            if event_data.get("action") == "create_event":
                summary = event_data.get("summary")
                start_iso = event_data.get("start")
                end_iso = event_data.get("end")
                success, msg = add_calendar_event(summary, start_iso, end_iso)
                if success:
                    # 格式化顯示時間
                    clean_start = start_iso.replace("T", " ")[:16]
                    reply_text = f"✅ 已成功為您排入 Google 日曆！\n\n📌 活動：{summary}\n⏰ 時間：{clean_start}"
                else:
                    reply_text = f"寫入日曆失敗，原因：{msg}"
            else:
                reply_text = res_text
        else:
            reply_text = res_text

    except Exception as e:
        reply_text = f"處理時發生錯誤：{str(e)}"

    with ApiClient(configuration) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

if __name__ == "__main__":
    app.run(port=5000)
