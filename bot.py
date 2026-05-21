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
MY_PHONE = os.environ["YOUR_PHONE"]  # Your default number
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
ALLOWED_USER = os.environ.get("TELEGRAM_USER_ID", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# PHONE_BOOK format in Railway: "GF:+919876543210,Mom:+919876543211"
PHONE_BOOK = {}
pb_raw = os.environ.get("PHONE_BOOK", "")
if pb_raw:
    for entry in pb_raw.split(","):
        if ":" in entry:
            name, number = entry.split(":", 1)
            PHONE_BOOK[name.strip().lower()] = number.strip()

DATA_DIR = "/data" if os.path.isdir("/data") else "."
REMINDERS_FILE = os.path.join(DATA_DIR, "reminders.json")
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


# ── Phone lookup ───────────────────────────────────────
def resolve_phone(who=None):
    """Resolve a name to a phone number. Returns (phone, display_name)."""
    if not who or who.lower() in ("me", "myself", "self", ""):
        return MY_PHONE, "me"
    key = who.lower().strip()
    if key in PHONE_BOOK:
        return PHONE_BOOK[key], who
    # Fuzzy: check if any phonebook name contains the key or vice versa
    for name, number in PHONE_BOOK.items():
        if key in name or name in key:
            return number, who
    return MY_PHONE, "me"


# ── Twilio ─────────────────────────────────────────────
def make_call(message, phone=None):
    """Call a single phone. Returns call SID."""
    client = Client(TWILIO_SID, TWILIO_AUTH)
    target = phone or MY_PHONE
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
    call = client.calls.create(twiml=twiml, to=target, from_=TWILIO_PHONE)
    return call.sid


# ── Auth ───────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    if not ALLOWED_USER:
        return True
    return str(update.effective_user.id) == ALLOWED_USER


# ── Helper: add a single reminder ─────────────────────
def add_single_reminder(message, time_str, reminders, who=None):
    """Validate and add one reminder. Returns (reminder, error_string)."""
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None, f"Invalid time format: {time_str}"

    now = datetime.now(tz)
    call_dt = dt.replace(tzinfo=tz)
    if call_dt < now:
        return None, f"Time {time_str} is in the past (now: {now.strftime('%Y-%m-%d %H:%M')})"

    phone, display_name = resolve_phone(who)

    reminder = {
        "id": next_id(reminders),
        "message": message,
        "call_time": time_str,
        "phone": phone,
        "who": display_name,
        "status": "pending"
    }
    reminders.append(reminder)
    return reminder, None


def format_time_until(time_str):
    """Return human-friendly 'Xd Yh from now' string."""
    now = datetime.now(tz)
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    diff = dt - now
    days = diff.days
    hours = diff.seconds // 3600
    mins = (diff.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h from now"
    elif hours > 0:
        return f"{hours}h {mins}m from now"
    else:
        return f"{mins}m from now"


# ── Bot commands ───────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    contacts = "  me (default)"
    for name in PHONE_BOOK:
        contacts += f"\n  {name}"
    await update.message.reply_text(
        "CallMe Bot\n\n"
        "Just type naturally:\n"
        "  remind me to call Bachcha at 10:17\n"
        "  cancel Netflix trial tomorrow at 9am\n"
        "  call me 3 times to cancel Grok: 7pm, 8pm, 9pm\n"
        "  remind GF to take medicine at 8pm\n\n"
        "Or use commands:\n"
        "/add Cancel Netflix trial | 2026-05-25 10:00\n"
        "/list — Show all reminders\n"
        "/remove 3 — Remove reminder #3\n"
        "/clear — Remove completed reminders\n"
        "/test — Make a test call now\n"
        "/contacts — Show phonebook\n"
        "/myid — Show your Telegram user ID\n\n"
        f"Contacts:\n{contacts}"
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

    reminders = load_reminders()
    reminder, error = add_single_reminder(message, time_str, reminders)

    if error:
        await update.message.reply_text(error)
        return

    save_reminders(reminders)
    tu = format_time_until(time_str)

    await update.message.reply_text(
        f"Added #{reminder['id']}\n"
        f"{message}\n"
        f"Call at: {time_str} IST ({tu})"
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
            who = r.get("who", "me")
            who_tag = f" [{who}]" if who != "me" else ""
            text += f"  #{r['id']}  {r['call_time']}  {r['message']}{who_tag}\n"

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


async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not PHONE_BOOK:
        await update.message.reply_text(
            "No contacts configured.\n\n"
            "Add PHONE_BOOK variable in Railway:\n"
            "GF:+919876543210,Mom:+919876543211"
        )
        return
    lines = ["Phonebook:"]
    for name, number in PHONE_BOOK.items():
        lines.append(f"  {name} → {number}")
    lines.append(f"\nDefault (me) → {MY_PHONE}")
    await update.message.reply_text("\n".join(lines))


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
            target_phone = r.get("phone", MY_PHONE)
            who = r.get("who", "me")
            try:
                sid = make_call(r["message"], phone=target_phone)
                r["status"] = "done"
                r["called_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                r["call_sid"] = sid
                changed = True

                if ALLOWED_USER:
                    try:
                        who_tag = f" [{who}]" if who != "me" else ""
                        await context.bot.send_message(
                            chat_id=int(ALLOWED_USER),
                            text=f"Called for #{r['id']}: {r['message']}{who_tag}"
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
                            text=f"FAILED #{r['id']}: {r['message']}\nError: {e}"
                        )
                    except Exception:
                        pass

    if changed:
        save_reminders(reminders)


# ── Natural language parsing via Groq ──────────────────
def parse_with_groq(user_text):
    """Send user text to Groq LLM. Returns (list_of_reminders, error_string)."""
    if not GROQ_API_KEY:
        return None, "GROQ_API_KEY not set in Railway variables"

    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    weekday = now.strftime("%A")

    # Build contacts list for the prompt
    contact_names = ", ".join(PHONE_BOOK.keys()) if PHONE_BOOK else "none configured"

    system_prompt = f"""You extract reminders from natural language.
Today is {weekday}, {today}. Current time is {current_time} IST.

The user may give you ONE or MULTIPLE reminders in a single message.

For EACH reminder, extract:
1. "message" — what to remind about (clean, concise, imperative form)
2. "datetime" — when to call, format YYYY-MM-DD HH:MM (24-hour)
3. "who" — who to call. Default is "me". If the user says "remind GF", "tell Mom", "call GF" etc, use that name. Known contacts: {contact_names}

Handle relative times:
- "at 10:17" = today at 10:17 (if not passed yet), else tomorrow
- "tomorrow at 9am" = tomorrow 09:00
- "in 2 hours" = current time + 2 hours
- "next Monday at 3pm" = next Monday 15:00
- "day after tomorrow" = {today} + 2 days
- "two days from now" = {today} + 2 days

If the user gives one reminder with multiple times (e.g. "call me 3 times: 7pm, 8pm, 9pm"), create SEPARATE reminders for each time with the same message.

If a reminder has no specific time, default to 09:00 on that day.
If a reminder has no specific date but has a time, use today (or tomorrow if the time has passed).

ALWAYS return a JSON array, even for a single reminder. No markdown, no backticks, no explanation:
[{{"message": "...", "datetime": "YYYY-MM-DD HH:MM", "who": "me"}}]

Example with contact:
[{{"message": "Take your medicine", "datetime": "2026-05-20 20:00", "who": "GF"}}]

If you cannot parse anything valid, return:
[]"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                "temperature": 0,
                "max_tokens": 500
            },
            timeout=15
        )

        if resp.status_code != 200:
            return None, f"Groq API error {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        logger.info(f"Groq raw response: {text}")
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            parsed = [parsed]

        valid = [p for p in parsed if p.get("message") and p.get("datetime")]
        if valid:
            return valid, None
        return None, f"LLM returned no valid reminders. Raw: {text[:200]}"

    except json.JSONDecodeError:
        return None, f"LLM returned invalid JSON: {text[:200]}"
    except KeyError:
        return None, f"Unexpected Groq response format: {str(data)[:200]}"
    except requests.Timeout:
        return None, "Groq API timed out (15s)"
    except Exception as e:
        logger.error(f"Groq parse error: {e}")
        return None, f"Error: {e}"


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

    await update.message.chat.send_action("typing")

    parsed_list, error = parse_with_groq(text)

    if not parsed_list:
        error_detail = f"\n\nDebug: {error}" if error else ""
        await update.message.reply_text(
            f"Couldn't parse that as a reminder.{error_detail}\n\n"
            "Try something like:\n"
            "  remind me to call Bachcha at 10:17\n"
            "  cancel Grok at 7pm, 8pm, 9pm day after tomorrow\n"
            "  remind GF to take medicine at 8pm\n"
            "Or use: /add Message | 2026-05-18 10:17"
        )
        return

    reminders = load_reminders()
    added = []
    errors = []

    for item in parsed_list:
        who = item.get("who", "me")
        reminder, err = add_single_reminder(item["message"], item["datetime"], reminders, who=who)
        if reminder:
            added.append(reminder)
        else:
            errors.append(f"{item['message']}: {err}")

    save_reminders(reminders)

    lines = []
    for r in added:
        tu = format_time_until(r["call_time"])
        who_tag = f" [{r['who']}]" if r.get("who", "me") != "me" else ""
        lines.append(f"#{r['id']}  {r['message']}{who_tag}\n     {r['call_time']} IST ({tu})")

    if lines:
        response = f"Added {len(lines)} reminder{'s' if len(lines) > 1 else ''}:\n\n" + "\n\n".join(lines)
    else:
        response = ""

    if errors:
        response += "\n\nErrors:\n" + "\n".join(errors)

    await update.message.reply_text(response)


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
    app.add_handler(CommandHandler("contacts", cmd_contacts))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Natural language — catches any plain text that isn't a command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_message))

    # Check reminders every 30 seconds
    app.job_queue.run_repeating(check_reminders, interval=30, first=5)

    logger.info("CallMe bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
