# Yad2Bot

Telegram bot that scrapes Yad2 used cars and sends new matches to you.

## Quick start (Docker — recommended)

```bash
cp .env.example .env
# Edit .env with your BOT_TOKEN and TELEGRAM_USER_ID
docker compose up -d
```

Logs:
```bash
docker compose logs -f
```

Stop:
```bash
docker compose down
```

The SQLite database is stored in a named Docker volume (`yad2bot_data`) and survives container restarts/rebuilds.

## Local setup (without Docker)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your BOT_TOKEN and TELEGRAM_USER_ID
python main.py
```

## Getting credentials

- **BOT_TOKEN**: Talk to [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`
- **TELEGRAM_USER_ID**: Talk to [@userinfobot](https://t.me/userinfobot) to get your numeric ID

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize bot and start scanning |
| `/status` | Show current config and next scan time |
| `/scan` | Trigger a manual scan immediately |
| `/config` | Open interactive settings menu |

## Config options (via /config)

- **Brands** – multi-select from popular brands (Toyota, Mazda, Honda, etc.)
- **Price range** – min/max in ₪
- **Max KM** – odometer ceiling
- **Year range** – min/max model year
- **Hand** – up to 1st / 2nd / 3rd / any
- **Scan interval** – 15min / 30min / 1hr / 2hr / 6hr / 12hr
- **Max results per scan** – 1 / 3 / 5 / 10 / unlimited

## Notes

- Only sends listings not previously seen (tracked in SQLite)
- Silent when no new results
- Random 2–5s delay between requests to be polite to Yad2
- Single-user bot — only responds to the configured `TELEGRAM_USER_ID`
