# 🎁 WishReserveBot

Telegram bot for creating wish lists with a **gift reservation** feature.  
Share your wishes with friends and prevent duplicate gifts!

## ✨ Features

- **Create** wish lists with multiple items
- **Share** wish lists with friends via links
- **Reserve** gifts so nobody buys the same thing twice
- **Private/public** wish lists with subscription approval
- **Multi-language** support (English / Русский)

## 🛠 Tech Stack

- Python 3.12+ / aiogram 3.x
- SQLAlchemy + aiosqlite
- FSM (Finite State Machine) for form handling
- i18n middleware for multi-language support

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/stephanvoytov/WishReserveBot.git
cd WishReserveBot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your bot token and admin IDs

# 4. Run the bot
python main.py
```

## 📋 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and see main menu |
| `/help` | Show help information |

## 🔒 Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `ADMIN_IDS` | Comma-separated admin Telegram user IDs |
| `DB_URL` | Database connection string (default: sqlite) |

## 📁 Project Structure

```
WishReserveBot/
├── main.py                 # Entry point
├── config/                 # Configuration
├── database/               # Models and DB requests
├── handlers/               # Bot message/callback handlers
├── keyboards/              # Inline keyboard markup
├── middlewares/            # i18n and logging middleware
├── filters/                # Custom filters
├── states/                 # FSM states
├── lexicon/                # Multi-language strings
└── external_services/      # External integrations
```