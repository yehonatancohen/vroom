import logging
import asyncio
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
import scraper
import formatter
from config import (
    BOT_TOKEN,
    TELEGRAM_USER_ID,
    SUPPORTED_BRANDS,
    INTERVAL_OPTIONS,
    MAX_RESULTS_OPTIONS,
    HAND_OPTIONS,
    DEFAULT_CONFIG,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_next_scan_time: datetime | None = None


# ---------------------------------------------------------------------------
# Guard: only allow the configured user
# ---------------------------------------------------------------------------

def _authorized(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid == TELEGRAM_USER_ID


async def _deny(update: Update):
    if update.message:
        await update.message.reply_text("⛔ Unauthorized.")
    elif update.callback_query:
        await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------

async def run_scan(app: Application):
    global _next_scan_time
    cfg = db.get_config()
    logger.info("Running scan with config: %s", cfg)

    since = db.get_last_scan_time()
    scan_started_at = datetime.now()

    loop = asyncio.get_event_loop()
    listings = await loop.run_in_executor(None, scraper.scrape, cfg, since)
    db.set_last_scan_time(scan_started_at)

    if not listings:
        logger.info("Scan returned 0 results.")
        _schedule_next(app, cfg.get("scan_interval", 30))
        return

    # Filter unseen
    all_ids = [l.listing_id for l in listings]
    new_ids = set(db.filter_new(all_ids))
    new_listings = [l for l in listings if l.listing_id in new_ids]

    if not new_listings:
        logger.info("No new listings.")
        _schedule_next(app, cfg.get("scan_interval", 30))
        return

    max_results = cfg.get("max_results", 5)
    if max_results > 0:
        new_listings = new_listings[:max_results]

    for listing in new_listings:
        text = formatter.format_listing(listing)
        try:
            if listing.image_url:
                await app.bot.send_photo(
                    chat_id=TELEGRAM_USER_ID,
                    photo=listing.image_url,
                    caption=text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await app.bot.send_message(
                    chat_id=TELEGRAM_USER_ID,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False,
                )
        except Exception as e:
            logger.warning("Failed to send listing %s: %s", listing.listing_id, e)
            # Fallback: send without photo
            try:
                await app.bot.send_message(
                    chat_id=TELEGRAM_USER_ID,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False,
                )
            except Exception as e2:
                logger.error("Fallback send also failed: %s", e2)

    db.mark_seen([l.listing_id for l in new_listings])
    logger.info("Sent %d new listings.", len(new_listings))
    _schedule_next(app, cfg.get("scan_interval", 30))


def _schedule_next(app: Application, interval_minutes: int):
    global _next_scan_time
    _next_scan_time = datetime.now() + timedelta(minutes=interval_minutes)

    job_id = "periodic_scan"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        run_scan,
        "interval",
        minutes=interval_minutes,
        args=[app],
        id=job_id,
        replace_existing=True,
        next_run_time=_next_scan_time,
    )
    logger.info("Next scan in %d minutes at %s", interval_minutes, _next_scan_time.strftime("%H:%M"))


# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)
    db.init_db()
    cfg = db.get_config()
    text = (
        "👋 ברוך הבא ל־Yad2Bot\\!\n\n"
        "הבוט יסרוק את יד2 ויישלח לך מכוניות חדשות לפי ההגדרות שלך\\.\n\n"
        "פקודות זמינות:\n"
        "/config – הגדרות\n"
        "/status – סטטוס נוכחי\n"
        "/scan – סריקה ידנית עכשיו\n"
        "/url – הצג או שנה URL חיפוש מותאם"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    _schedule_next(context.application, cfg.get("scan_interval", 30))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)
    cfg = db.get_config()
    config_text = formatter.format_config(cfg)

    next_str = (
        _next_scan_time.strftime("%H:%M:%S")
        if _next_scan_time
        else "לא מתוזמן"
    )
    text = f"{config_text}\n\n⏰ סריקה הבאה: {next_str}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)
    await update.message.reply_text("🔍 מתחיל סריקה...")
    await run_scan(context.application)


async def cmd_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)
    args = context.args
    if not args:
        cfg = db.get_config()
        current = cfg.get("search_url") or "לא מוגדר (נבנה מהגדרות)"
        await update.message.reply_text(
            f"🔗 *URL חיפוש נוכחי:*\n`{current}`\n\n"
            "לשינוי: `/url <url>`\n"
            "לאיפוס להגדרות: `/url reset`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    value = args[0].strip()
    if value == "reset":
        db.set_config_key("search_url", "")
        await update.message.reply_text("✅ URL אופס — ייבנה מהגדרות.")
    else:
        db.set_config_key("search_url", value)
        await update.message.reply_text(f"✅ URL עודכן:\n`{value}`", parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# /config inline keyboard flow
# ---------------------------------------------------------------------------

def _config_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🏷 מותגים", callback_data="cfg:brands")],
        [InlineKeyboardButton("💰 טווח מחיר", callback_data="cfg:price")],
        [InlineKeyboardButton("🛣 ק\"מ מקסימום", callback_data="cfg:km")],
        [InlineKeyboardButton("📅 טווח שנים", callback_data="cfg:year")],
        [InlineKeyboardButton("✋ יד", callback_data="cfg:hand")],
        [InlineKeyboardButton("⏱ תדירות סריקה", callback_data="cfg:interval")],
        [InlineKeyboardButton("📊 מקסימום תוצאות", callback_data="cfg:maxresults")],
        [InlineKeyboardButton("🔄 איפוס להגדרות ברירת מחדל", callback_data="cfg:reset")],
    ]
    return InlineKeyboardMarkup(buttons)


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)
    await update.message.reply_text(
        "⚙️ *הגדרות* – בחר קטגוריה:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_config_main_keyboard(),
    )


# --- Brands ---

def _brands_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for brand in SUPPORTED_BRANDS:
        check = "✅ " if brand in selected else ""
        rows.append([InlineKeyboardButton(f"{check}{brand}", callback_data=f"brand:{brand}")])
    rows.append([InlineKeyboardButton("✔️ סיום", callback_data="cfg:done")])
    return InlineKeyboardMarkup(rows)


async def _show_brands(query, cfg):
    await query.edit_message_text(
        "🏷 בחר מותגים (לחץ לסימון/ביטול):",
        reply_markup=_brands_keyboard(cfg.get("brands", [])),
    )


# --- Interval ---

def _interval_keyboard(current: int) -> InlineKeyboardMarkup:
    rows = []
    for val, label in INTERVAL_OPTIONS:
        check = "✅ " if val == current else ""
        rows.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"interval:{val}")])
    rows.append([InlineKeyboardButton("◀️ חזרה", callback_data="cfg:back")])
    return InlineKeyboardMarkup(rows)


# --- Max results ---

def _maxresults_keyboard(current: int) -> InlineKeyboardMarkup:
    rows = []
    for val, label in MAX_RESULTS_OPTIONS:
        check = "✅ " if val == current else ""
        rows.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"maxresults:{val}")])
    rows.append([InlineKeyboardButton("◀️ חזרה", callback_data="cfg:back")])
    return InlineKeyboardMarkup(rows)


# --- Hand ---

def _hand_keyboard(current: int) -> InlineKeyboardMarkup:
    rows = []
    for val, label in HAND_OPTIONS:
        check = "✅ " if val == current else ""
        rows.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"hand:{val}")])
    rows.append([InlineKeyboardButton("◀️ חזרה", callback_data="cfg:back")])
    return InlineKeyboardMarkup(rows)


# --- Price / KM / Year (text input) ---

AWAITING = {}  # user_id -> what we're waiting for


async def _prompt_text_input(query, field: str, hint: str):
    AWAITING[query.from_user.id] = field
    await query.edit_message_text(f"✏️ {hint}\n\nשלח את הערך כהודעת טקסט.")


# ---------------------------------------------------------------------------
# Callback handler
# ---------------------------------------------------------------------------

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _authorized(update):
        return await _deny(update)
    await query.answer()

    data = query.data
    cfg = db.get_config()

    if data == "cfg:brands":
        await _show_brands(query, cfg)

    elif data.startswith("brand:"):
        brand = data[len("brand:"):]
        brands = list(cfg.get("brands", []))
        if brand in brands:
            brands.remove(brand)
        else:
            brands.append(brand)
        db.set_config_key("brands", brands)
        cfg["brands"] = brands
        await _show_brands(query, cfg)

    elif data == "cfg:interval":
        await query.edit_message_text(
            "⏱ בחר תדירות סריקה:",
            reply_markup=_interval_keyboard(cfg.get("scan_interval", 30)),
        )

    elif data.startswith("interval:"):
        val = int(data.split(":")[1])
        db.set_config_key("scan_interval", val)
        _schedule_next(context.application, val)
        await query.edit_message_text(
            f"✅ תדירות סריקה עודכנה.",
            reply_markup=_config_main_keyboard(),
        )

    elif data == "cfg:maxresults":
        await query.edit_message_text(
            "📊 בחר מקסימום תוצאות לסריקה:",
            reply_markup=_maxresults_keyboard(cfg.get("max_results", 5)),
        )

    elif data.startswith("maxresults:"):
        val = int(data.split(":")[1])
        db.set_config_key("max_results", val)
        await query.edit_message_text(
            "✅ מקסימום תוצאות עודכן.",
            reply_markup=_config_main_keyboard(),
        )

    elif data == "cfg:hand":
        await query.edit_message_text(
            "✋ בחר עד איזו יד:",
            reply_markup=_hand_keyboard(cfg.get("hand_max", 0)),
        )

    elif data.startswith("hand:"):
        val = int(data.split(":")[1])
        db.set_config_key("hand_max", val)
        await query.edit_message_text(
            "✅ הגדרת יד עודכנה.",
            reply_markup=_config_main_keyboard(),
        )

    elif data == "cfg:price":
        await _prompt_text_input(
            query,
            "price",
            f"טווח מחיר נוכחי: ₪{cfg.get('price_min', 0):,} – ₪{cfg.get('price_max', 200000):,}\n"
            "שלח בפורמט: מינימום-מקסימום  (למשל: 30000-120000)",
        )

    elif data == "cfg:km":
        await _prompt_text_input(
            query,
            "km",
            f"ק\"מ מקסימום נוכחי: {cfg.get('km_max', 300000):,}\n"
            "שלח מספר (למשל: 150000)",
        )

    elif data == "cfg:year":
        await _prompt_text_input(
            query,
            "year",
            f"טווח שנים נוכחי: {cfg.get('year_min', 2010)} – {cfg.get('year_max', 2025)}\n"
            "שלח בפורמט: מינימום-מקסימום  (למשל: 2015-2022)",
        )

    elif data == "cfg:reset":
        db.reset_config()
        cfg = db.get_config()
        _schedule_next(context.application, cfg.get("scan_interval", 30))
        await query.edit_message_text(
            "✅ ההגדרות אופסו לברירת המחדל.",
            reply_markup=_config_main_keyboard(),
        )

    elif data in ("cfg:back", "cfg:done"):
        await query.edit_message_text(
            "⚙️ *הגדרות* – בחר קטגוריה:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_config_main_keyboard(),
        )


# ---------------------------------------------------------------------------
# Text message handler (for price/km/year input)
# ---------------------------------------------------------------------------

from telegram.ext import MessageHandler, filters


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return await _deny(update)

    user_id = update.effective_user.id
    field = AWAITING.pop(user_id, None)
    if field is None:
        return  # Not expecting input

    text = (update.message.text or "").strip()

    try:
        if field == "km":
            val = int(text.replace(",", "").replace(" ", ""))
            db.set_config_key("km_max", val)
            await update.message.reply_text(f"✅ ק\"מ מקסימום עודכן ל־{val:,}.")

        elif field == "price":
            parts = text.replace(" ", "").split("-")
            price_min = int(parts[0].replace(",", ""))
            price_max = int(parts[1].replace(",", ""))
            db.set_config_key("price_min", price_min)
            db.set_config_key("price_max", price_max)
            await update.message.reply_text(
                f"✅ טווח מחיר עודכן: ₪{price_min:,} – ₪{price_max:,}."
            )

        elif field == "year":
            parts = text.replace(" ", "").split("-")
            year_min = int(parts[0])
            year_max = int(parts[1])
            db.set_config_key("year_min", year_min)
            db.set_config_key("year_max", year_max)
            await update.message.reply_text(
                f"✅ טווח שנים עודכן: {year_min} – {year_max}."
            )

    except (ValueError, IndexError):
        await update.message.reply_text("❌ פורמט שגוי. נסה שוב עם /config.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in .env")
    if not TELEGRAM_USER_ID:
        raise RuntimeError("TELEGRAM_USER_ID is not set in .env")

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("url", cmd_url))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    scheduler.start()

    # Schedule initial scan
    cfg = db.get_config()
    _schedule_next(app, cfg.get("scan_interval", 30))

    logger.info("Bot started. Listening...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
