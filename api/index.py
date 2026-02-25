from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
import sys
import os
import httpx
import asyncio
import hashlib
import hmac

# Añadir el directorio raíz al path para importar los módulos locales
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crew_logic import run_odoo_crew
from config import (
    WHATSAPP_VERIFY_TOKEN, WHATSAPP_API_TOKEN, 
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET,
    API_SECRET_KEY
)

app = FastAPI(title="Odoo CrewAI Agent API")

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
        return True  # Si no hay secret configurado, permitir (dev mode)
    if not signature_header:
        return False
    
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(), request_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)

def _check_bearer_token(request: Request) -> bool:
    """Valida el Bearer Token en el header Authorization."""
    if not API_SECRET_KEY:
        return True  # Si no hay key configurada, permitir (dev mode)
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET_KEY}"


@app.get("/api")
def root():
    return {"status": "Agente Odoo Activo"}

# ==========================================
# ENDPOINT DE CHAT GENÉRICO (Pruebas Web)
# ==========================================
@app.post("/api/chat")
async def chat(request: Request):
    # --- Autenticación ---
    if not _check_bearer_token(request):
        return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    try:
        data = await request.json()
        session_id = data.get("session_id", "default_session")
        message = data.get("message")
        
        if not message:
            return JSONResponse(status_code=400, content={"error": "Falta el mensaje"})
        
        # Ejecutar en hilo separado para no bloquear el event loop
        result = await asyncio.to_thread(run_odoo_crew, session_id, message)
        
        return {
            "reply": str(result),
            "session_id": session_id
        }
    except Exception as e:
        print(f"[ERROR /api/chat] {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"error": "Error interno del servidor."})

# ==========================================
# ENDPOINTS WHATSAPP CLOUD API
# ==========================================

@app.get("/api/whatsapp")
async def verify_webhook(request: Request):
    """
    Endpoint para verificación del Webhook de Meta.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            print("WEBHOOK_VERIFIED")
            return Response(content=challenge, media_type="text/plain", status_code=200)
        else:
            return Response(status_code=403)
    return Response(content="Hello WhatsApp Webhook", status_code=200)


async def send_whatsapp_message(phone_number: str, message_text: str):
    """
    Envía una respuesta de texto usando la Graph API de WhatsApp.
    """
    if not WHATSAPP_API_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("[WARN] Faltan credenciales de WhatsApp")
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
        "text": {
            "body": message_text
        }
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in [200, 201]:
                print(f"[ERROR WhatsApp Send] Status {response.status_code}")
            else:
                print(f"[OK] Mensaje enviado a {_mask_phone(phone_number)}")
        except Exception as e:
            print(f"[ERROR WhatsApp HTTP] {type(e).__name__}")


def process_whatsapp_message(phone_number: str, user_message: str):
    """
    Función síncrona/blocking que ejecuta CrewAI y luego envía la respuesta.
    Ideal para ejecutar en BackgroundTasks.
    """
    print(f"[CrewAI] Procesando mensaje de {_mask_phone(phone_number)}")
    
    try:
        # Ejecutar la inteligencia de enjambre
        result = run_odoo_crew(session_id=phone_number, user_message=user_message)
        final_text = str(result)
        
        asyncio.run(send_whatsapp_message(phone_number, final_text))
        
    except Exception as e:
        print(f"[ERROR CrewAI] {type(e).__name__}: {e}")
        error_msg = ("Disculpa, estoy experimentando dificultades técnicas. "
                     "Por favor, inténtalo de nuevo en unos minutos. 🙏")
        asyncio.run(send_whatsapp_message(phone_number, error_msg))


@app.post("/api/whatsapp")
async def receive_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe los mensajes (POST) desde Meta.
    Valida firma, marca leído e inicia procesamiento en segundo plano.
    """
    try:
        body_bytes = await request.body()
        
        # --- Validación de firma de Meta ---
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_meta_signature(body_bytes, signature):
            print("[SECURITY] Firma de Meta inválida. Request rechazado.")
            return Response(status_code=403)
        
        import json
        body = json.loads(body_bytes)
        
        # Validar estructura del payload de WhatsApp
        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # Ignorar eventos que no sean mensajes entrantes
                    if "messages" in value:
                        message = value["messages"][0]
                        phone_number = value["contacts"][0]["wa_id"]
                        
                        # Extraer solo el texto
                        if message.get("type") == "text":
                            msg_text = message["text"]["body"]
                            
                            # Enviar a CrewAI en SEGUNDO PLANO
                            background_tasks.add_task(process_whatsapp_message, phone_number, msg_text)
                            
        # SIEMPRE retornar 200 INMEDIATAMENTE
        return Response(status_code=200)

    except Exception as e:
        print(f"[ERROR Webhook] {type(e).__name__}")
        return Response(status_code=200)  # Siempre 200 a Meta para evitar reintentos

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
