import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0"))

DB_PATH = os.getenv("DB_PATH", "yad2bot.db")

FB_LOCATION_ID = os.getenv("FB_LOCATION_ID", "")  # set to override; empty = use IP geolocation

DEFAULT_CONFIG = {
    "brands": [],           # empty = all brands
    "model_filter": [],     # empty = all models; list of substrings matched against listing title
    "price_min": 0,
    "price_max": 200000,
    "km_max": 300000,
    "year_min": 2010,
    "year_max": 2025,
    "hand_max": 3,          # 0 = any
    "scan_interval": 30,    # minutes
    "max_results": 5,       # 0 = unlimited
    "search_url": "",       # if set, overrides the built URL
}

SUPPORTED_BRANDS = [
    "טויוטה",    # Toyota
    "מאזדה",     # Mazda
    "הונדה",     # Honda
    "יונדאי",    # Hyundai
    "קיה",       # Kia
    "סקודה",     # Skoda
    "פולקסווגן", # Volkswagen
    "פורד",      # Ford
    "סוזוקי",    # Suzuki
    "ניסאן",     # Nissan
    "מיצובישי",  # Mitsubishi
    "שברולט",    # Chevrolet
    "אופל",      # Opel
    "סיטרואן",   # Citroen
    "פיג'ו",     # Peugeot
    "רנו",       # Renault
    "סאב",       # Saab
    "וולוו",     # Volvo
    "דייהטסו",   # Daihatsu
]

INTERVAL_OPTIONS = [
    (15, "15 דקות"),
    (30, "30 דקות"),
    (60, "שעה"),
    (120, "שעתיים"),
    (360, "6 שעות"),
    (720, "12 שעות"),
    (1440, "24 שעות"),
    (10080, "שבוע"),
]

MAX_RESULTS_OPTIONS = [
    (1, "1"),
    (3, "3"),
    (5, "5"),
    (10, "10"),
    (0, "ללא הגבלה"),
]

HAND_OPTIONS = [
    (1, "יד ראשונה"),
    (2, "עד יד שנייה"),
    (3, "עד יד שלישית"),
    (0, "הכל"),
]

YAD2_BASE_URL = "https://www.yad2.co.il/vehicles/cars"
YAD2_API_URL = "https://gw.yad2.co.il/feed-search-legacy/vehicles/cars"
