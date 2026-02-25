import os

# --- Validación de entorno ---
def _require_env(key: str) -> str:
    """Exige que una variable de entorno esté definida."""
    val = os.getenv(key, "")
    if not val:
        print(f"[CONFIG WARNING] Variable de entorno '{key}' no definida.")
    return val

# Odoo Credentials
ODOO_URL = _require_env("ODOO_URL")
ODOO_DB = _require_env("ODOO_DB")
ODOO_USERNAME = _require_env("ODOO_USERNAME")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

# Supabase Credentials
SUPABASE_URL = _require_env("SUPABASE_URL")
SUPABASE_KEY = _require_env("SUPABASE_KEY")

# OpenAI Configuration
OPENAI_API_KEY = _require_env("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

# WhatsApp API Credentials
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")

# API Authentication
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# Email (Resend)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Sofía de Real to Digital <sofia@realtodigital3d.com>")
