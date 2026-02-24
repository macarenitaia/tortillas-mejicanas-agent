from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
import json

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def save_message(session_id: str, role: str, content: str):
    """Guarda un mensaje en la tabla 'messages'."""
    try:
        data = {
            "session_id": session_id,
            "role": role,
            "content": content
        }
        supabase.table("messages").insert(data).execute()
        print(f"Mensaje de {role} guardado en memoria.")
    except Exception as e:
        print(f"Error guardando mensaje en Supabase: {e}")

def get_recent_messages(session_id: str, limit: int = 5) -> str:
    """Recupera los últimos N mensajes de la sesión para dar contexto al Agente."""
    try:
        # Se obtiene el historial ordenado por id o created_at descendente (asumiendo que tiene created_at)
        res = supabase.table("messages").select("role, content").eq("session_id", session_id).order("id", desc=True).limit(limit).execute()
        
        if not res.data:
            return "No hay historial previo de conversación."
            
        # Transformarlo a cadena de texto de contexto (los más viejos primero)
        messages_str = "Historial reciente de esta conversación (útil para no volver a pedir datos):\n"
        for msg in reversed(res.data):
            messages_str += f"[{msg['role'].upper()}]: {msg['content']}\n"
        
        return messages_str
    except Exception as e:
        print(f"Error recuperando historial: {e}")
        return "No se pudo recuperar el historial debido a un error técnico."

class SupabaseMemoryTool(BaseTool):
    name: str = "Save Conversation"
    description: str = "Saves a message to the conversation history in Supabase for long-term memory. Provide session_id, role (agent/user), and content."

    def _run(self, session_id: str, role: str, content: str) -> str:
        save_message(session_id, role, content)
        return "Message saved to memory."
