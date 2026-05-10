import os
import requests
import subprocess
import json

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def start_of_day_utc():
    now = datetime.now(timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())


TOKEN = os.getenv("TOKEN_ID")
CHAT_ID = int(os.getenv("CHAT_ID"))

API_URL = "http://127.0.0.1:8081/v2/data"
HISTORY_URL = "http://127.0.0.1:8081/v2/history"

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

DASHBOARD_SERVICE = "miner_dashboardv2.service"


# -------------------------
# Telegram helpers
# -------------------------
def is_authorized(update):
    try:
        res = update
        if "callback_query" in update:
            res = update["callback_query"]
        if "message" in res:
            return res["message"]["chat"]["id"] == CHAT_ID

    except Exception:
        return False

    return False

def send_message(text, reply_markup=None):
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)


# -------------------------
# Keyboard
# -------------------------

def send_main_menu():
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "⛏ BITAXE 1  ", "callback_data": "miner_1"},
                {"text": "⛏ BITAXE 2  ", "callback_data": "miner_2"},
            ],
            [
                {"text": "📊 STATUS  ", "callback_data": "status"},
                {"text": "📊 TOP  ", "callback_data": "top"}
            ],
            [
                {"text": "🔄 RESTART DASHBOARD", "callback_data": "restart_dashboard"}
            ]
        ]
    }

    send_message("Select action:", keyboard)


# -------------------------
# Data source
# -------------------------

def get_data():
    r = requests.get(API_URL, timeout=5)
    r.raise_for_status()
    return r.json()["items"]

def get_history(day_ts):
    r = requests.get(HISTORY_URL, params={"t": day_ts}, timeout=10)
    r.raise_for_status()
    return r.json()

# -------------------------
# Miner formatter
# -------------------------
def human_readable_diff(diff):
    '''Returns a human readable representation of hashrate.'''

    if diff < 1000:
        return '%.2f' % diff
    if diff < 1000000:
        return '%.2fK' % (diff / 1000)
    if diff < 1000000000:
        return '%.2fM' % (diff / 1000000)

    return '%.2fG' % (diff / 1000000000)

def format_miner(miner):
    return (
        f"⛏ <b>{miner['Miner name']}</b>\n"
        f"ID: {miner['Miner id']}\n\n"
        f"⚡ Hashrate: {miner['Reported Hashrate']}\n"
        f"🔥 Best diff: {miner['Best diff']}\n"
        f"🏆 Best ever: {human_readable_diff(miner['Best diff ever'])}\n"
        f"🌡 Temp: {miner['Temp']}\n"
        f"🔌 Power: {miner['Power']}\n"
        f"📈 Shares: {miner['Shares']}\n"
        f"⏱ Uptime: {miner['Uptime']}"
    )


# -------------------------
# System status
# -------------------------

def system_status():
    try:
        output = subprocess.check_output(
            ["systemctl", "status", "miner_dashboardv2.service", "--no-pager"],
            stderr=subprocess.STDOUT
        ).decode()

        # recortamos para Telegram
        return f"<pre>{output[-3500:]}</pre>"

    except Exception as e:
        return f"Error systemctl: {e}"


def handle_top():
    try:
        day_ts = start_of_day_utc()
        data = get_history(day_ts)

        if not data:
            return "📊 No data available"

        # ordenar por dificultad descendente
        top5 = sorted(data, key=lambda x: x["d"], reverse=True)[:5]

        msg = ["🏆 <b>TOP 5 TODAY</b>\n"]

        for i, item in enumerate(top5, 1):
            ts_local = datetime.fromtimestamp(item["t"], tz=ZoneInfo("Europe/Madrid"))
            msg.append(f"{i}. 🔥 {human_readable_diff(item['d'])}  (Miner {item['m']} - ⏱ {ts_local.strftime('%H:%M:%S')})\n")

        return "\n".join(msg)

    except Exception as e:
        return f"❌ Error TOP: {e}"

def restart_dashboard():
    try:
        send_message("🔄 Restarting dashboard...")
        subprocess.run(
            ["systemctl", "restart", DASHBOARD_SERVICE],
            check=True
        )
        send_message("🔄 Dashboard restarted successfully")

    except Exception as e:
        send_message(f"❌ Failed to restart dashboard:\n{e}")
# -------------------------
# Callback router
# -------------------------

def handle_callback(data):
    try:
        if data == "status":
            msg = system_status()
            send_message(msg)
            return

        if data == "top":
            msg = handle_top()
            send_message(msg)
            return

        if data.startswith("miner_"):
            miner_id = int(data.split("_")[1])

            items = get_data()

            miner = next((m for m in items if m["Miner id"] == miner_id), None)

            if not miner:
                send_message("❌ Miner not found")
                return

            send_message(format_miner(miner))
            return

        if data == "restart_dashboard":
            restart_dashboard()
            return

    except Exception as e:
        send_message(f"❌ Error: {e}")


# -------------------------
# Polling loop
# -------------------------

def poll():
    offset = None

    while True:
        try:
            url = f"{TELEGRAM_API}/getUpdates"

            params = {
                "timeout": 30,
                "offset": offset
            }

            r = requests.get(url, params=params, timeout=35)
            data = r.json()

            for result in data.get("result", []):

                offset = result["update_id"] + 1
                if not is_authorized(result):
                    print(f"Unauthorized attempt: {result}")
                    continue

                if "callback_query" in result:
                    query = result["callback_query"]

                    handle_callback(query["data"])

                    # respond to Telegram callback (removes loading animation)
                    requests.post(
                        f"{TELEGRAM_API}/answerCallbackQuery",
                        json={"callback_query_id": query["id"]}
                    )

                elif "message" in result:
                    # text = result["message"].get("text", "")
                    # if text == "/start":
                    send_main_menu()

        except Exception as e:
            print("poll error:", e)


if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        raise Exception("Missing TOKEN_ID or CHAT_ID env vars")

    print("Bot running...")
    poll()