"""
CallMe Bot — Telegram bot that calls you with reminders via Twilio.
Add/remove/list reminders from Telegram. Runs 24/7 on Railway.
"""

import os
import json
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from twilio.rest import Client

# ── Config from environment variables ──────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TWILIO_SID = os.environ["TWILIO_SID"]
TWILIO_AUTH = os.environ["TWILIO_AUTH"]
TWILIO_PHONE = os.environ["TWILIO_PHONE"]
YOUR_PHONE = os.environ["YOUR_PHONE"]
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
ALLOWED_USER = os.environ.get("TELEGRAM_USER_ID", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

REMINDERS_FILE = "reminders.json"
tz = ZoneInfo(TIMEZONE)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("callme")


# ── Storage ────────────────────────────────────────────
def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE) as f:
        return json.load(f)


def save_reminders(reminders):
    with open(REMINDERS_FILE, "w") as f:
        json.dump(reminders, f, indent=2, ensure_ascii=False)


def next_id(reminders):
    if not reminders:
        return 1
    return max(r["id"] for r in reminders) + 1


# ── Twilio ─────────────────────────────────────────────
def make_call(message):
    client = Client(TWILIO_SID, TWILIO_AUTH)
    twiml = (
        f'<Response>'
        f'<Say voice="Google.en-IN-Standard-B" language="en-IN">'
        f'Hello. This is your reminder.</Say>'
        f'<Pause length="1"/>'
        f'<Say voice="Google.en-IN-Standard-B" language="en-IN">{message}</Say>'
        f'<Pause length="2"/>'
        f'<Say voice="Google.en-IN-Standard-B" language="en-IN">'
        f'Repeating. {message}</Say>'
        f'<Pause length="1"/>'
        f'<Say voice="Google.en-IN-Standard-B" language="en-IN">'
        f'End of reminder. Goodbye.</Say>'
        f'</Response>'
    )
    call = client.calls.create(twiml=twiml, to=YOUR_PHONE, from_=TWILIO_PHONE)
    return call.sid


# ── Auth ───────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    if not ALLOWED_USER:
        return True
    return str(update.effective_user.id) == ALLOWED_USER


# ── Bot commands ───────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    await update.message.reply_text(
        "CallMe Bot\n\n"
        "Just type naturally:\n"
        "  remind me to call Bachcha at 10:17\n"
        "  cancel Netflix trial tomorrow at 9am\n\n"
        "Or use commands:\n"
        "/add Cancel Netflix trial | 2026-05-25 10:00\n"
        "/list — Show all reminders\n"
        "/remove 3 — Remove reminder #3\n"
        "/clear — Remove completed reminders\n"
        "/test — Make a test call now\n"
        "/myid — Show your Telegram user ID"
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    text = update.message.text.replace("/add", "", 1).strip()

    if "|" not in text:
        await update.message.reply_text(
            "Format:\n/add Cancel Netflix trial | 2026-05-25 10:00\n\n"
            "The message goes before the | and the date/time after."
        )
        return

    parts = text.split("|", 1)
    message = parts[0].strip()
    time_str = parts[1].strip()

    # Try parsing the datetime
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text(
            "Could not parse the time.\n"
            "Use format: YYYY-MM-DD HH:MM\n"
            "Example: 2026-05-25 10:00"
        )
        return

    # Check if the time is in the past
    now = datetime.now(tz)
    call_dt = dt.replace(tzinfo=tz)
    if call_dt < now:
        await update.message.reply_text(
            f"That time ({time_str}) is in the past.\n"
            f"Current time: {now.strftime('%Y-%m-%d %H:%M')} IST"
        )
        return

    reminders = load_reminders()
    reminder = {
        "id": next_id(reminders),
        "message": message,
        "call_time": time_str,
        "status": "pending"
    }
    reminders.append(reminder)
    save_reminders(reminders)

    # Calculate days/hours until call
    diff = call_dt - now
    days = diff.days
    hours = diff.seconds // 3600
    mins = (diff.seconds % 3600) // 60

    time_until = ""
    if days > 0:
        time_until = f"{days}d {hours}h from now"
    elif hours > 0:
        time_until = f"{hours}h {mins}m from now"
    else:
        time_until = f"{mins}m from now"

    await update.message.reply_text(
        f"Added #{reminder['id']}\n"
        f"{message}\n"
        f"Call at: {time_str} IST ({time_until})"
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    reminders = load_reminders()
    pending = [r for r in reminders if r["status"] == "pending"]
    done = [r for r in reminders if r["status"] == "done"]
    failed = [r for r in reminders if r["status"] == "failed"]

    if not reminders:
        await update.message.reply_text("No reminders. Add one with:\n/add Message here | 2026-05-25 10:00")
        return

    text = ""
    if pending:
        text += "PENDING:\n"
        for r in sorted(pending, key=lambda x: x["call_time"]):
            text += f"  #{r['id']}  {r['call_time']}  {r['message']}\n"

    if done:
        text += "\nDONE:\n"
        for r in done[-5:]:
            text += f"  #{r['id']}  {r['call_time']}  {r['message']}\n"

    if failed:
        text += "\nFAILED:\n"
        for r in failed:
            text += f"  #{r['id']}  {r['call_time']}  {r['message']}\n"

    await update.message.reply_text(text)


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove 3")
        return

    try:
        rid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /remove 3 (use the reminder number)")
        return

    reminders = load_reminders()
    original = len(reminders)
    removed_msg = None
    for r in reminders:
        if r["id"] == rid:
            removed_msg = r["message"]
            break
    reminders = [r for r in reminders if r["id"] != rid]

    if len(reminders) == original:
        await update.message.reply_text(f"No reminder #{rid}")
        return

    save_reminders(reminders)
    await update.message.reply_text(f"Removed #{rid}: {removed_msg}")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    reminders = load_reminders()
    pending = [r for r in reminders if r["status"] == "pending"]
    removed = len(reminders) - len(pending)
    save_reminders(pending)
    await update.message.reply_text(f"Cleared {removed} completed/failed reminders.")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    await update.message.reply_text("Placing test call...")
    try:
        sid = make_call("This is a test. Your reminder system is working.")
        await update.message.reply_text(f"Call placed. Your phone should ring soon.\nSID: {sid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        f"Your Telegram user ID: {uid}\n\n"
        f"Set this as TELEGRAM_USER_ID in Railway to lock the bot to only you."
    )


# ── Scheduler ──────────────────────────────────────────
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(tz)
    reminders = load_reminders()
    changed = False

    for r in reminders:
        if r["status"] != "pending":
            continue

        call_time = datetime.strptime(r["call_time"], "%Y-%m-%d %H:%M").replace(tzinfo=tz)

        if now >= call_time:
            logger.info(f"FIRING #{r['id']}: {r['message']}")
            try:
                sid = make_call(r["message"])
                r["status"] = "done"
                r["called_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                r["call_sid"] = sid
                changed = True

                # Also notify on Telegram
                if ALLOWED_USER:
                    try:
                        await context.bot.send_message(
                            chat_id=int(ALLOWED_USER),
                            text=f"Called you for #{r['id']}: {r['message']}"
                        )
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Call failed for #{r['id']}: {e}")
                r["status"] = "failed"
                r["error"] = str(e)
                changed = True

                if ALLOWED_USER:
                    try:
                        await context.bot.send_message(
                            chat_id=int(ALLOWED_USER),
                            text=f"FAILED to call for #{r['id']}: {r['message']}\nError: {e}"
                        )
                    except Exception:
                        pass

    if changed:
        save_reminders(reminders)


# ── Natural language parsing via Groq ──────────────────
def parse_with_groq(user_text):
    """Send user text to Groq LLM to extract reminder message and datetime."""
    if not GROQ_API_KEY:
        return None

    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    weekday = now.strftime("%A")

    system_prompt = f"""You extract reminders from natural language. 
Today is {weekday}, {today}. Current time is {current_time} IST.

Extract:
1. "message" — what to remind about (clean, concise, imperative form, e.g. "Call Bachcha", "Cancel Netflix trial")
2. "datetime" — when to call, in format YYYY-MM-DD HH:MM

Handle relative times:
- "at 10:17" = today at 10:17 (if not passed), else tomorrow
- "tomorrow at 9am" = tomorrow 09:00
- "in 2 hours" = {current_time} + 2 hours
- "next Monday at 3pm" = next Monday 15:00

Return ONLY a JSON object, no markdown, no backticks, no explanation:
{{"message": "...", "datetime": "YYYY-MM-DD HH:MM"}}

If you cannot parse a valid reminder, return:
{{"message": null, "datetime": null}}"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                "temperature": 0,
                "max_tokens": 150
            },
            timeout=10
        )
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        # Clean any markdown fences
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if parsed.get("message") and parsed.get("datetime"):
            return parsed
        return None
    except Exception as e:
        logger.error(f"Groq parse error: {e}")
        return None


async def handle_natural_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages as natural language reminders."""
    if not is_authorized(update):
        return

    text = update.message.text.strip()
    if not text:
        return

    if not GROQ_API_KEY:
        await update.message.reply_text(
            "Natural language not enabled (no GROQ_API_KEY).\n"
            "Use: /add Message | YYYY-MM-DD HH:MM"
        )
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    parsed = parse_with_groq(text)

    if not parsed:
        await update.message.reply_text(
            "Couldn't parse that as a reminder.\n"
            "Try something like: remind me to call Bachcha at 10:17\n"
            "Or use: /add Call Bachcha | 2026-05-18 10:17"
        )
        return

    message = parsed["message"]
    time_str = parsed["datetime"]

    # Validate the datetime
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text(f"LLM returned invalid time: {time_str}. Use /add instead.")
        return

    now = datetime.now(tz)
    call_dt = dt.replace(tzinfo=tz)
    if call_dt < now:
        await update.message.reply_text(
            f"That time ({time_str}) is in the past.\n"
            f"Current time: {now.strftime('%Y-%m-%d %H:%M')} IST"
        )
        return

    reminders = load_reminders()
    reminder = {
        "id": next_id(reminders),
        "message": message,
        "call_time": time_str,
        "status": "pending"
    }
    reminders.append(reminder)
    save_reminders(reminders)

    diff = call_dt - now
    days = diff.days
    hours = diff.seconds // 3600
    mins = (diff.seconds % 3600) // 60

    time_until = ""
    if days > 0:
        time_until = f"{days}d {hours}h from now"
    elif hours > 0:
        time_until = f"{hours}h {mins}m from now"
    else:
        time_until = f"{mins}m from now"

    await update.message.reply_text(
        f"Added #{reminder['id']}\n"
        f"{message}\n"
        f"Call at: {time_str} IST ({time_until})"
    )


# ── Main ───────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Natural language — catches any plain text that isn't a command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_message))

    # Check reminders every 30 seconds
    app.job_queue.run_repeating(check_reminders, interval=30, first=5)

    logger.info("CallMe bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
