from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
from typing import Optional
from logger import get_logger

log = get_logger("supabase_tools")

# Inicializar cliente Supabase globalmente
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _mask_phone(phone: str) -> str:
    """Enmascara teléfono para logs seguros."""
    if len(phone) > 4:
        return f"***{phone[-4:]}"
    return "***"


def _get_tenant_id() -> Optional[str]:
    """Busca o crea el tenant_id de 'Real to Digital'."""
    try:
        res = supabase.table("organizations").select("id").eq("name", "Real to Digital").limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        
        insert_res = supabase.table("organizations").insert({"name": "Real to Digital"}).execute()
        log.info("Tenant 'Real to Digital' created")
        return insert_res.data[0]["id"]
    except Exception as e:
        log.error(f"tenant_id error: {type(e).__name__}")
        return None


def _get_or_create_lead_id(phone: str, tenant_id: str) -> Optional[str]:
    """Busca o crea un lead_id real en la tabla leads."""
    if not tenant_id:
        return None
        
    try:
        res = supabase.table("leads").select("id").eq("phone", phone).eq("tenant_id", tenant_id).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
            
        new_lead = {"name": "Cliente de WhatsApp", "phone": phone, "tenant_id": tenant_id}
        insert_res = supabase.table("leads").insert(new_lead).execute()
        log.info(f"Lead created for {_mask_phone(phone)}")
        return insert_res.data[0]["id"]
    except Exception as e:
        log.error(f"lead_id error: {type(e).__name__}")
        return None


def save_message(session_phone: str, role: str, content: str) -> None:
    """Guarda un mensaje en la tabla 'messages'."""
    try:
        db_role = 'assistant' if role.lower() in ('agente', 'assistant') else 'user'
        
        tenant_id = _get_tenant_id()
        lead_id = _get_or_create_lead_id(session_phone, tenant_id)
        
        if not tenant_id or not lead_id:
            log.warning("Aborted save: missing tenant/lead")
            return

        data = {
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "role": db_role,
            "content": content
        }
        supabase.table("messages").insert(data).execute()
        log.info(f"Message '{db_role}' saved for {_mask_phone(session_phone)}")
    except Exception as e:
        log.error(f"save_message error: {type(e).__name__}")


def get_recent_messages(session_phone: str, limit: int = 5) -> str:
    """Recupera los últimos N mensajes para contexto conversacional."""
    try:
        tenant_id = _get_tenant_id()
        lead_id = _get_or_create_lead_id(session_phone, tenant_id)
        
        if not tenant_id or not lead_id:
            return "No hay historial previo de conversación."
        
        res = (supabase.table("messages")
               .select("role, content")
               .eq("lead_id", lead_id)
               .eq("tenant_id", tenant_id)
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        
        if not res.data:
            return "No hay historial previo de conversación."
            
        messages_str = "Historial reciente de esta conversación (útil para no volver a pedir datos):\n"
        for msg in reversed(res.data):
            display_role = "AGENTE" if msg['role'] == "assistant" else "USUARIO"
            messages_str += f"[{display_role}]: {msg['content']}\n"
        
        return messages_str
    except Exception as e:
        log.error(f"get_recent_messages error: {type(e).__name__}")
        return "No se pudo recuperar el historial."


class SupabaseMemoryTool(BaseTool):
    """Herramienta de CrewAI para guardar mensajes en Supabase."""
    name: str = "Save Conversation"
    description: str = "Saves a message to conversation history. Provide session_id, role (agent/user), and content."

    def _run(self, session_id: str, role: str, content: str) -> str:
        save_message(session_id, role, content)
        return "Message saved to memory."
