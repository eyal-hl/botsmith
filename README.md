# Pi Helper Bot

A self-programming Telegram bot for Raspberry Pi. Talk to it in natural language to create scheduled messages, custom commands, and more — all running locally without needing an LLM at execution time.

## Quick Setup

### 1. Prerequisites
- Raspberry Pi 4/5 with Pi OS (64-bit) and Python 3.11+
- A Telegram Bot Token (talk to [@BotFather](https://t.me/BotFather))
- A Claude API key from [console.anthropic.com](https://console.anthropic.com)

### 2. Install

```bash
git clone <your-repo-url> ~/pi-helper-bot
cd ~/pi-helper-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
nano .env
```

Fill in:
- `TELEGRAM_TOKEN` — from BotFather
- `CLAUDE_API_KEY` — your Anthropic API key
- `ALLOWED_USER_IDS` — your Telegram user ID (send `/start` to [@userinfobot](https://t.me/userinfobot) to find it)
- `LOCATION_LAT` / `LOCATION_LON` — your default location
- `TIMEZONE` — e.g. `Asia/Jerusalem`

### 4. Run

```bash
# Test manually first
python -m bot.main

# Then install as a service
sudo cp mybot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mybot
sudo systemctl start mybot

# Check logs
journalctl -u mybot -f
```

### 5. Set up git backup

```bash
cd ~/pi-helper-bot
git init
git remote add origin git@github.com:you/pi-helper-bot.git
git add -A
git commit -m "Initial setup"
git push -u origin main
```

## Usage

Just send messages to your bot:

- **"Send me weather every morning at 7am on workdays"** → Creates a scheduled skill
- **"Create a /manchester command for Man United's next game"** → Creates a command skill
- **"Remember I prefer Celsius"** → Updates bot memory
- **"What time is it?"** → Direct chat response

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/skills` | List all skills |
| `/run <id>` | Test a skill manually |
| `/enable <id>` | Enable a disabled skill |
| `/disable <id>` | Disable a skill |
| `/delete <id>` | Delete a skill |
| `/newskill` | Step-by-step skill creation |
| `/memory` | Show bot memory |
| `/cancel` | Cancel current operation |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical documentation.

**Key principle**: LLM is used only at skill *creation* time. At runtime, skills execute as pure local Python: HTTP fetch → Jinja2 template → Telegram message. No LLM, no cloud dependency.
