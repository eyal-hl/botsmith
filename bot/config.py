import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Telegram
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_IDS: set[int] = {
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}

# Claude
CLAUDE_API_KEY: str = os.environ["CLAUDE_API_KEY"]
CLAUDE_CLASSIFICATION_MODEL: str = "claude-haiku-4-5-20251001"
CLAUDE_GENERATION_MODEL: str = "claude-sonnet-4-20250514"

# Location & timezone
LOCATION_LAT: float = float(os.environ.get("LOCATION_LAT", "32.08"))
LOCATION_LON: float = float(os.environ.get("LOCATION_LON", "34.78"))
TIMEZONE: str = os.environ.get("TIMEZONE", "Asia/Jerusalem")

# Git
GIT_AUTO_PUSH: bool = os.environ.get("GIT_AUTO_PUSH", "true").lower() == "true"
GIT_BRANCH: str = os.environ.get("GIT_BRANCH", "main")

# API keys
FOOTBALL_API_KEY: str = os.environ.get("FOOTBALL_API_KEY", "")

# Paths
SKILLS_DIR: Path = BASE_DIR / "skills"
PLUGINS_DIR: Path = BASE_DIR / "plugins"
MEMORY_FILE: Path = BASE_DIR / "memory.md"
CHANGELOG_FILE: Path = BASE_DIR / "changelog.md"
CACHE_DB: Path = BASE_DIR / "data" / "cache.db"

# Limits
MAX_SKILLS: int = 50
MAX_SKILL_CREATIONS_PER_HOUR: int = 5
SKILL_EXECUTION_TIMEOUT: int = 30

# Domain whitelist for skill HTTP fetches
DOMAIN_WHITELIST: set[str] = {
    "api.open-meteo.com",
    "api.football-data.org",
    "wttr.in",
    "api.exchangerate-api.com",
    "newsapi.org",
    "api.github.com",
    "api.coingecko.com",
}
extra = os.environ.get("EXTRA_DOMAINS", "")
if extra:
    DOMAIN_WHITELIST.update(d.strip() for d in extra.split(",") if d.strip())

# Cache TTLs (seconds) by domain
CACHE_TTLS: dict[str, int] = {
    "api.open-meteo.com": 1800,       # 30 min
    "api.football-data.org": 21600,    # 6 hours
    "wttr.in": 1800,                   # 30 min
    "api.exchangerate-api.com": 3600,  # 1 hour
    "default": 900,                    # 15 min fallback
}

# Ensure directories exist
SKILLS_DIR.mkdir(exist_ok=True)
PLUGINS_DIR.mkdir(exist_ok=True)
CACHE_DB.parent.mkdir(exist_ok=True)
