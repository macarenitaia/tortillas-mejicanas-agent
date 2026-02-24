from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
import sys
import os
import httpx
import asyncio

# Añadir el directorio raíz al path para importar los módulos locales
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crew_logic import run_odoo_crew
from config import WHATSAPP_VERIFY_TOKEN, WHATSAPP_API_TOKEN, WHATSAPP_PHONE_NUMBER_ID

app = FastAPI(title="Odoo CrewAI Agent API")

@app.get("/api")
def root():
    return {"status": "Agente Odoo Activo", "workspace": "crewAI"}

# ==========================================
# ENDPOINT DE CHAT GENÉRICO (Pruebas Web)
# ==========================================
@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
        session_id = data.get("session_id", "default_session")
        message = data.get("message")
        
        if not message:
            return JSONResponse(status_code=400, content={"error": "Falta el mensaje"})
            
        result = run_odoo_crew(session_id, message)
        
        return {
            "reply": str(result),
            "session_id": session_id
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

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
        print("Faltan credenciales de WhatsApp (WHATSAPP_API_TOKEN o WHATSAPP_PHONE_NUMBER_ID)")
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
                print(f"Error enviando mensaje WhatsApp: {response.text}")
            else:
                print(f"Mensaje WhatsApp enviado exitosamente a {phone_number}")
        except Exception as e:
            print(f"Excepción HTTP al enviar WhatsApp: {e}")


def process_whatsapp_message(phone_number: str, user_message: str):
    """
    Función síncrona/blocking que ejecuta CrewAI y luego envía la respuesta.
    Ideal para ejecutar en BackgroundTasks.
    """
    print(f"Iniciando CrewAI para {phone_number} con mensaje: {user_message}")
    
    try:
        # Ejecutar la inteligencia de enjambre (esto toma su tiempo)
        result = run_odoo_crew(session_id=phone_number, user_message=user_message)
        final_text = str(result)
        
        # Como httpx es asíncrono y corremos esto en un hilo nativo de BackgroundTasks,
        # necesitamos un bucle de eventos para mandarlo.
        asyncio.run(send_whatsapp_message(phone_number, final_text))
        
    except Exception as e:
        print(f"Error en process_whatsapp_message para {phone_number}: {e}")
        error_msg = ("Ups, ha habido un problema técnico procesando tu mensaje. "
                     "Por favor, inténtalo de nuevo en unos minutos.")
        asyncio.run(send_whatsapp_message(phone_number, error_msg))


@app.post("/api/whatsapp")
async def receive_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe los mensajes (POST) desde Meta.
    Verifica payload, marca leído e inicia procesamiento en segundo plano.
    """
    try:
        body = await request.json()
        
        # Validar estructura del payload de WhatsApp
        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # Ignorar eventos que no sean mensajes entrantes (ej. confirmaciones de lectura)
                    if "messages" in value:
                        message = value["messages"][0]
                        phone_number = value["contacts"][0]["wa_id"]
                        
                        # Extraer solo el texto (si el usuario mandó texto)
                        if message.get("type") == "text":
                            msg_text = message["text"]["body"]
                            
                            # Enviar a CrewAI en SEGUNDO PLANO
                            background_tasks.add_task(process_whatsapp_message, phone_number, msg_text)
                            
        # SIEMPRE retornar 200 INMEDIATAMENTE para que Meta no se sature ni reintente
        return Response(status_code=200)

    except Exception as e:
        print(f"Error procesando webhook entrante: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
