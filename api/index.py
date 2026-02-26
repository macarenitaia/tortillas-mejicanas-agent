from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
import sys
import os
import httpx
import asyncio
import hashlib
import hmac
import time
from collections import defaultdict
from typing import Dict, Tuple

# Añadir el directorio raíz al path para importar los módulos locales
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crew_logic import run_odoo_crew
from config import (
    WHATSAPP_VERIFY_TOKEN, WHATSAPP_API_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET,
    API_SECRET_KEY
)
from logger import get_logger

log = get_logger("api")

app = FastAPI(title="Tortillas Mejicanas WhatsApp Agent API")

# ==========================================
# UTILIDADES DE SEGURIDAD
# ==========================================

def _mask_phone(phone: str) -> str:
    """Enmascara un número de teléfono para logs seguros."""
    if len(phone) > 4:
        return f"***{phone[-4:]}"
    return "***"

def _verify_meta_signature(request_body: bytes, signature_header: str) -> bool:
    """Valida la firma X-Hub-Signature-256 de Meta."""
    if not WHATSAPP_APP_SECRET:
        return True  # Dev mode
    if not signature_header:
        return False
    expected = "sha256=" + hmac.HMAC(
        WHATSAPP_APP_SECRET.encode(), request_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)

def _check_bearer_token(request: Request) -> bool:
    """Valida el Bearer Token en el header Authorization."""
    if not API_SECRET_KEY:
        return True  # Dev mode
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET_KEY}"

# ==========================================
# RATE LIMITER (In-Memory, por IP)
# ==========================================

class RateLimiter:
    """Rate limiter simple basado en ventana deslizante por IP."""
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, client_ip: str) -> bool:
        """Devuelve True si la IP no ha excedido el límite."""
        now = time.time()
        # Limpiar timestamps viejos
        self._requests[client_ip] = [
            t for t in self._requests[client_ip]
            if now - t < self.window_seconds
        ]
        if len(self._requests[client_ip]) >= self.max_requests:
            return False
        self._requests[client_ip].append(now)
        return True

rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# ==========================================
# DEDUPLICACIÓN DE WEBHOOKS
# ==========================================

class MessageDedup:
    """Previene el procesamiento duplicado de mensajes de WhatsApp."""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._seen: Dict[str, float] = {}
    
    def is_duplicate(self, message_id: str) -> bool:
        """Devuelve True si el message_id ya fue procesado recientemente."""
        now = time.time()
        # Limpiar entradas expiradas periódicamente
        if len(self._seen) > 1000:
            self._seen = {k: v for k, v in self._seen.items() if now - v < self.ttl}
        
        if message_id in self._seen:
            return True
        self._seen[message_id] = now
        return False

message_dedup = MessageDedup(ttl_seconds=300)

# ==========================================
# HEALTH CHECK
# ==========================================

@app.get("/api")
def root():
    return {"status": "ok", "service": "odoo-whatsapp-agent", "version": "1.0.0"}

@app.get("/api/health")
async def health_check():
    """Health check con estado de dependencias externas."""
    checks = {"api": "ok"}
    
    # Check Supabase
    try:
        from tools_supabase import supabase
        supabase.table("organizations").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception:
        checks["supabase"] = "error"
    
    # Check Odoo
    try:
        from tools_odoo import odoo
        odoo._ensure_authenticated()
        checks["odoo"] = "ok"
    except Exception:
        checks["odoo"] = "error"
    
    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "healthy" if all_ok else "degraded", "checks": checks}
    )

# ==========================================
# ENDPOINT DE CHAT GENÉRICO (Pruebas Web)
# ==========================================
@app.post("/api/chat")
async def chat(request: Request):
    # --- Autenticación ---
    if not _check_bearer_token(request):
        return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    # --- Rate Limiting ---
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        log.warning(f"Rate limit exceeded for IP {client_ip[:8]}***")
        return JSONResponse(status_code=429, content={"error": "Demasiadas peticiones. Intenta en un minuto."})
    
    try:
        data = await request.json()
        session_id: str = data.get("session_id", "default_session")
        message: str = data.get("message", "")
        
        if not message:
            return JSONResponse(status_code=400, content={"error": "Falta el mensaje"})
        
        # Ejecutar en hilo separado para no bloquear el event loop
        result = await asyncio.to_thread(run_odoo_crew, session_id, message)
        
        return {"reply": str(result), "session_id": session_id}
    except Exception as e:
        log.error(f"/api/chat error: {type(e).__name__}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Error interno del servidor."})

# ==========================================
# ENDPOINTS WHATSAPP CLOUD API
# ==========================================

@app.get("/api/whatsapp")
async def verify_webhook(request: Request):
    """Endpoint para verificación del Webhook de Meta (GET)."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            log.info("Webhook verified by Meta")
            return Response(content=challenge, media_type="text/plain", status_code=200)
        else:
            return Response(status_code=403)
    return Response(content="OK", status_code=200)


async def send_whatsapp_message(phone_number: str, message_text: str) -> None:
    """Envía una respuesta de texto usando la Graph API de WhatsApp."""
    if not WHATSAPP_API_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log.warning("WhatsApp credentials missing")
        return

    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {"body": message_text}
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in [200, 201]:
                log.info(f"WhatsApp message sent to {_mask_phone(phone_number)}")
            else:
                log.error(f"WhatsApp send failed: HTTP {response.status_code}")
        except Exception as e:
            log.error(f"WhatsApp HTTP error: {type(e).__name__}")


def process_whatsapp_message(phone_number: str, user_message: str) -> None:
    """Función síncrona que ejecuta CrewAI y envía la respuesta. Corre en BackgroundTasks."""
    log.info(f"Processing message from {_mask_phone(phone_number)}")
    
    try:
        result = run_odoo_crew(session_id=phone_number, user_message=user_message)
        final_text = str(result)
        asyncio.run(send_whatsapp_message(phone_number, final_text))
    except Exception as e:
        log.error(f"CrewAI error: {type(e).__name__}", exc_info=True)
        error_msg = ("Disculpa, estoy experimentando dificultades técnicas. "
                     "Por favor, inténtalo de nuevo en unos minutos. 🙏")
        asyncio.run(send_whatsapp_message(phone_number, error_msg))


@app.post("/api/whatsapp")
async def receive_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """Recibe mensajes POST desde Meta. Valida firma, deduplica, y procesa en background."""
    try:
        body_bytes = await request.body()
        
        # --- Validación de firma de Meta ---
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_meta_signature(body_bytes, signature):
            log.warning("Invalid Meta signature rejected")
            return Response(status_code=403)
        
        import json
        body = json.loads(body_bytes)
        
        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    if "messages" in value:
                        message = value["messages"][0]
                        phone_number: str = value["contacts"][0]["wa_id"]
                        message_id: str = message.get("id", "")
                        
                        # --- Deduplicación ---
                        if message_dedup.is_duplicate(message_id):
                            log.info(f"Duplicate message {message_id[:8]}*** skipped")
                            return Response(status_code=200)
                        
                        if message.get("type") == "text":
                            msg_text: str = message["text"]["body"]
                            background_tasks.add_task(process_whatsapp_message, phone_number, msg_text)
                            
        return Response(status_code=200)

    except Exception as e:
        log.error(f"Webhook error: {type(e).__name__}", exc_info=True)
        return Response(status_code=200)  # Siempre 200 a Meta

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
