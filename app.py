import os
import re
import json
from datetime import datetime
import pytz
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v為了避免手動替換局部程式碼時容易出現縮排錯誤或漏掉 `import`，**最安全、最直接的做法就是「整份全部覆蓋」**！

請將 GitHub 裡的 `app.py` 內容全部清空，直接貼上以下這份整合了 Google 日曆新增、推播功能、防呆正規表達式解析，以及當前可用模型 `gemini-3.6-flash` 的完整程式碼：

```python
import os
import re
import json
from datetime import datetime
import pytz
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 讀取雲端環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
MY_LINE_USER_ID = os.environ.get("MY_LINE_USER_ID")

app = Flask(__name__)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 設定 Gemini 模型
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.6-flash')

# 建立 Google 日曆連線服務
def get_calendar_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['[https://www.googleapis.com/auth/calendar](https://www.googleapis.com/auth/calendar)']
    )
    return build('calendar', 'v3', credentials=credentials)

# 寫入行程到 Google 日曆
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

# LINE Webhook 入口
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理收到的訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_message = event.message.text
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

        # 使用正規表達式精準抓取 JSON 區塊
        json_match = re.search(r'\{.*"action":\s*"create_event".*\}', res_text, re.DOTALL)
        
        if json_match:
            event_data = json.loads(json_match.group(0))
            summary = event_data.get("summary")
            start_iso = event_data.get("start")
            end_iso = event_data.get("end")
            
            success, msg = add_calendar_event(summary, start_iso, end_iso)
            if success:
                clean_start = start_iso.replace("T", " ")[:16]
                reply_text = f"✅ 已成功為您排入 Google 日曆！\n\n📌 活動：{summary}\n⏰ 時間：{clean_start}"
            else:
                reply_text = f"寫入日曆失敗，原因：{msg}"
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

# 主動推播提醒路由
@app.route("/push-reminder", methods=['GET'])
def push_reminder():
    if not MY_LINE_USER_ID:
        return "尚未設定 MY_LINE_USER_ID 環境變數", 400
    
    try:
        ai_prompt = "請幫我寫一句簡短、溫馨且充滿活力的早安問候，並提醒今天要注意開會與重要行程。"
        ai_response = model.generate_content(ai_prompt)
        reminder_text = ai_response.text
    except Exception as e:
        reminder_text = f"早安！記得今天有會議與重要行程要忙，祝你有個順利的一天！（AI生成略過: {e}）"

    try:
        with ApiClient(configuration) as api_client:
            line_api = MessagingApi(api_client)
            line_api.push_message_with_http_info(
                PushMessageRequest(
                    to=MY_LINE_USER_ID.strip(),
                    messages=[TextMessage(text=reminder_text)]
                )
            )
        return f"推播成功！已發送內容：<br>{reminder_text}"
    except Exception as e:
        return f"推播發送失敗，詳細原因：<br>{str(e)}", 500

if __name__ == "__main__":
    app.run(port=5000)
