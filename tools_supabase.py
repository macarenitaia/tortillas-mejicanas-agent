from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
import json

import uuid

def _get_or_create_lead_id(phone: str) -> str:
    """Busca o crea un lead_id sintético basado en el teléfono para poder guardar historial
    en una tabla que requiere UUID y no acepta el teléfono directamente."""
    try:
        # 1. Intentar buscar si este teléfono ya tiene un lead_id asignado en supabase
        res = supabase.table("leads").select("id").eq("phone", phone).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
            
        # 2. Si no existe, usamos un generador determinista (UUIDv5) basado en el teléfono
        # De esta forma, siempre que escriba el mismo teléfono, se asocia al mismo 'lead_id' sintético
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
        return str(uuid.uuid5(namespace, phone))
    except Exception as e:
        print(f"Error generando lead_id para teléfono: {e}")
        # Fallback a un UUID genérico sintético basado en el string para evitar crashear
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, phone))

def save_message(session_phone: str, role: str, content: str):
    """Guarda un mensaje en la tabla 'messages'.
       session_phone = número de whatsapp.
       role = 'user' o 'assistant'.
    """
    try:
        # Transformar el role al estándar de la DB capturada ('assistant' o 'user')
        db_role = 'assistant' if role.lower() == 'agente' else 'user'
        
        # Obtener el UUID asociado al nro de teléfono
        lead_id = _get_or_create_lead_id(session_phone)
        
        data = {
            "lead_id": lead_id,
            "role": db_role,
            "content": content
        }
        res = supabase.table("messages").insert(data).execute()
        print(f"Mensaje de '{db_role}' guardado en memoria. ID DB: {lead_id}")
    except Exception as e:
        print(f"Error crítico guardando mensaje en Supabase: {e}")

def get_recent_messages(session_phone: str, limit: int = 5) -> str:
    """Recupera los últimos N mensajes convirtiendo el teléfono a lead_id UUID."""
    try:
        lead_id = _get_or_create_lead_id(session_phone)
        
        # Recuperar buscando por lead_id
        res = supabase.table("messages").select("role, content").eq("lead_id", lead_id).order("created_at", desc=True).limit(limit).execute()
        
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
