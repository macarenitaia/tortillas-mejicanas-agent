import os

# Odoo Credentials
ODOO_URL = os.getenv("ODOO_URL", "https://real-to-digital-3d.odoo.com")
ODOO_DB = os.getenv("ODOO_DB", "real-to-digital-3d")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "angel@realtodigital3d.com")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

# Supabase Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rsbgkjkmvogbptpkklbm.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")

# WhatsApp API Credentials
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
