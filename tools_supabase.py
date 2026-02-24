from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
import json
import uuid

# Inicializar cliente Supabase globalmente
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def _get_tenant_id() -> str:
    """Busca o crea el tenant_id de 'Real to Digital' en la tabla organizations."""
    try:
        res = supabase.table("organizations").select("id").eq("name", "Real to Digital").limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        
        # Si no existe, lo creamos para que el agente tenga su espacio de trabajo
        insert_res = supabase.table("organizations").insert({"name": "Real to Digital"}).execute()
        print("Nuevo Tenant creado: Real to Digital")
        return insert_res.data[0]["id"]
    except Exception as e:
        print(f"Error obteniendo tenant_id: {e}")
        return None

def _get_or_create_lead_id(phone: str, tenant_id: str) -> str:
    """Busca o crea un lead_id real en la tabla leads."""
    if not tenant_id:
        return None
        
    try:
        res = supabase.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
            
        # Si no existe este número en los leads, creamos uno básico
        new_lead = {
            "name": "Cliente de WhatsApp",
            "phone": phone,
            "tenant_id": tenant_id
        }
        insert_res = supabase.table("leads").insert(new_lead).execute()
        print(f"Nuevo Lead creado para el teléfono {phone}")
        return insert_res.data[0]["id"]
    except Exception as e:
        print(f"Error generando/buscando lead_id para teléfono: {e}")
        return None

def save_message(session_phone: str, role: str, content: str):
    """Guarda un mensaje en la tabla 'messages'.
       session_phone = número de whatsapp.
       role = 'user' o 'assistant'.
    """
    try:
        # Transformar el role al estándar de la DB capturada ('assistant' o 'user')
        db_role = 'assistant' if role.lower() == 'agente' else 'user'
        
        # Jerarquía Multi-Tenant: Buscar Tenant -> Buscar Lead
        tenant_id = _get_tenant_id()
        lead_id = _get_or_create_lead_id(session_phone, tenant_id)
        
        if not tenant_id or not lead_id:
            print("Abortando guardado de memoria por falta de tenant o lead.")
            return

        data = {
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "role": db_role,
            "content": content
        }
        res = supabase.table("messages").insert(data).execute()
        print(f"Mensaje de '{db_role}' guardado en memoria BD.")
    except Exception as e:
        print(f"Error crítico guardando mensaje en Supabase: {e}")

def get_recent_messages(session_phone: str, limit: int = 5) -> str:
    """Recupera los últimos N mensajes convirtiendo el teléfono a lead_id UUID."""
    try:
        tenant_id = _get_tenant_id()
        lead_id = _get_or_create_lead_id(session_phone, tenant_id)
        
        if not tenant_id or not lead_id:
            return "No hay historial previo de conversación."
        
        # Recuperar buscando por lead_id y tenant_id por seguridad
        res = supabase.table("messages").select("role, content").eq("lead_id", lead_id).eq("tenant_id", tenant_id).order("created_at", desc=True).limit(limit).execute()
        
        if not res.data:
            return "No hay historial previo de conversación."
            
        messages_str = "Historial reciente de esta conversación (útil para no volver a pedir datos):\n"
        for msg in reversed(res.data):
            # Normalizar el rol para el Agente CrewAI
            display_role = "AGENTE" if msg['role'] == "assistant" else "USUARIO"
            messages_str += f"[{display_role}]: {msg['content']}\n"
        
        return messages_str
    except Exception as e:
        print(f"Error recuperando historial en Supabase: {e}")
        return "No se pudo recuperar el historial debido a un error técnico."

class SupabaseMemoryTool(BaseTool):
    name: str = "Save Conversation"
    description: str = "Saves a message to the conversation history in Supabase for long-term memory. Provide session_id, role (agent/user), and content."

    def _run(self, session_id: str, role: str, content: str) -> str:
        save_message(session_id, role, content)
        return "Message saved to memory."
