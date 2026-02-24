from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
import json

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


class SupabaseMemoryTool(BaseTool):
    name: str = "Save Conversation"
    description: str = "Saves a message to the conversation history in Supabase for long-term memory. Provide session_id, role (agent/user), and content."

    def _run(self, session_id: str, role: str, content: str) -> str:
        try:
            data = {
                "session_id": session_id,
                "role": role,
                "content": content
            }
            # Nota: Asumiendo que la tabla se llama 'messages' o 'conversations'
            res = supabase.table("messages").insert(data).execute()
            return "Message saved to memory."
        except Exception as e:
            return f"Error saving to memory: {str(e)}"
