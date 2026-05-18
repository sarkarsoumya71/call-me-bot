# CallMe Bot — Telegram + Twilio Reminder Calls

Add reminders from Telegram. Get phone calls at the right time. Runs 24/7 on Railway. PC doesn't need to be on.

## How it works

1. You message the Telegram bot: `/add Cancel Netflix trial | 2026-05-25 10:00`
2. Bot saves the reminder
3. At 10:00 AM IST on May 25, Twilio calls your phone and says the message
4. Bot also sends you a Telegram confirmation after the call

## Setup (one-time, ~10 minutes)

### Step 1: Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Pick a name (e.g., "CallMe Reminder")
4. Pick a username (e.g., "soumya_callme_bot") — must end in "bot"
5. BotFather gives you a **token** like `7123456789:AAH...` — save this

### Step 2: Get your Telegram user ID

1. Open Telegram, search for **@userinfobot**
2. Send it any message
3. It replies with your user ID (a number like `123456789`) — save this

### Step 3: Push to GitHub

1. Create a new repo on GitHub (e.g., "callme-bot")
2. Push these files to it:
```bash
cd callme-bot
git init
git add .
git commit -m "callme bot"
git remote add origin https://github.com/sarkarsoumya71/callme-bot.git
git push -u origin main
```

### Step 4: Deploy on Railway

1. Go to https://railway.com and sign in with GitHub
2. Click **New Project > Deploy from GitHub repo**
3. Select your callme-bot repo
4. Go to the deployed service > **Variables** tab
5. Add these environment variables:

| Variable | Value |
|----------|-------|
| `TELEGRAM_TOKEN` | The token from BotFather |
| `TWILIO_SID` | Your Twilio Account SID |
| `TWILIO_AUTH` | Your Twilio Auth Token |
| `TWILIO_PHONE` | `+18156833283` |
| `YOUR_PHONE` | `+919830949301` |
| `TIMEZONE` | `Asia/Kolkata` |
| `TELEGRAM_USER_ID` | Your Telegram user ID from Step 2 |

6. Railway auto-deploys. Check the logs — you should see "CallMe bot starting..."

### Step 5: Test

Open your bot in Telegram and send:
```
/test
```
Your phone should ring.

## Telegram Commands

```
/add Cancel Netflix trial | 2026-05-25 10:00   — Add a reminder
/list                                           — Show all reminders
/remove 3                                       — Remove reminder #3
/clear                                          — Remove completed reminders
/test                                           — Make a test call now
/myid                                           — Show your Telegram user ID
/help                                           — Show commands
```

## Cost

- Telegram bot: Free
- Railway: $5/month credit on Hobby plan (this bot uses ~$0.50-1/month of resources)
- Twilio: ~$1.15/month for the number + ~$0.02 per call
- Total: Effectively free within Railway's credit

## Notes

- The bot checks for due reminders every 30 seconds
- When a reminder fires, you get both a phone call AND a Telegram message
- Times are in IST (Asia/Kolkata). Change TIMEZONE env var if needed.
- Trial Twilio accounts play a disclaimer first — press any digit on your keypad to hear your message
- Reminders are stored in a JSON file. If Railway redeploys, pending reminders are lost. For a personal tool with few reminders, this is fine. You can always /list and re-add.
- TELEGRAM_USER_ID locks the bot so only you can use it. Without it, anyone who finds your bot can add reminders.
