from scraper import Listing
from typing import Optional


def format_listing(listing: Listing) -> str:
    lines = []

    lines.append(f"🚗 *{listing.title}*")

    if listing.price:
        lines.append(f"💰 ₪{listing.price:,}")
    else:
        lines.append("💰 מחיר לא צוין")

    details = []
    if listing.year:
        details.append(f"📅 {listing.year}")
    if listing.km is not None:
        details.append(f"🛣 {listing.km:,} ק\"מ")
    if listing.hand:
        details.append(f"✋ יד {listing.hand}")
    if listing.color:
        details.append(f"🎨 {listing.color}")
    if listing.city:
        details.append(f"📍 {listing.city}")

    if details:
        lines.append("  |  ".join(details))

    if listing.test_date:
        lines.append(f"🔧 טסט עד: {listing.test_date}")

    if listing.listed_at:
        lines.append(f"🕐 פורסם: {listing.listed_at.strftime('%d/%m/%Y %H:%M')}")

    lines.append(f"\n🔗 [לצפייה במודעה]({listing.listing_url})")

    return "\n".join(lines)


def format_plate_info(plate: str, info: Optional[dict]) -> str:
    if not info:
        return f"🔍 לוחית רישוי `{plate}` — לא נמצא מידע במאגר הממשלתי."

    lines = [f"🔍 *מידע רכב — {plate}*"]

    manufacturer = info.get("manufacturer", "")
    model = info.get("model", "")
    trim = info.get("trim", "")
    car_name = " ".join(p for p in [manufacturer, model, trim] if p)
    if car_name:
        lines.append(f"🚗 {car_name}")

    if info.get("year"):
        lines.append(f"📅 שנת ייצור: {info['year']}")
    if info.get("color"):
        lines.append(f"🎨 צבע: {info['color']}")
    if info.get("fuel"):
        lines.append(f"⛽ סוג דלק: {info['fuel']}")
    if info.get("engine_cc"):
        lines.append(f"🔧 נפח מנוע: {info['engine_cc']} סמ\"ק")
    if info.get("owner_count"):
        lines.append(f"✋ מספר בעלים: {info['owner_count']}")
    if info.get("ownership_type"):
        lines.append(f"🏢 בעלות: {info['ownership_type']}")
    if info.get("first_road_date"):
        lines.append(f"🛣 עלייה לכביש: {info['first_road_date']}")
    if info.get("test_valid_until"):
        lines.append(f"🔩 טסט בתוקף עד: {info['test_valid_until']}")
    elif info.get("last_test"):
        lines.append(f"🔩 טסט אחרון: {info['last_test']}")

    return "\n".join(lines)


def format_config(cfg: dict) -> str:
    from config import INTERVAL_OPTIONS, HAND_OPTIONS

    brands = cfg.get("brands", [])
    brands_str = ", ".join(brands) if brands else "הכל"

    model_filter = cfg.get("model_filter", [])
    models_str = ", ".join(model_filter) if model_filter else "הכל"

    interval_label = str(cfg.get("scan_interval", 30))
    for val, label in INTERVAL_OPTIONS:
        if val == cfg.get("scan_interval"):
            interval_label = label
            break

    hand_label = "הכל"
    for val, label in HAND_OPTIONS:
        if val == cfg.get("hand_max"):
            hand_label = label
            break

    max_res = cfg.get("max_results", 5)
    max_res_str = "ללא הגבלה" if max_res == 0 else str(max_res)

    lines = [
        "⚙️ *הגדרות נוכחיות*",
        f"🏷 מותגים: {brands_str}",
        f"🚘 דגמים: {models_str}",
        f"💰 מחיר: ₪{cfg.get('price_min', 0):,} – ₪{cfg.get('price_max', 200000):,}",
        f"🛣 ק\"מ מקסימום: {cfg.get('km_max', 300000):,}",
        f"📅 שנים: {cfg.get('year_min', 2010)} – {cfg.get('year_max', 2025)}",
        f"✋ יד: {hand_label}",
        f"⏱ סריקה כל: {interval_label}",
        f"📊 תוצאות מקסימום: {max_res_str}",
    ]
    return "\n".join(lines)
