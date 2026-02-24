from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from crewai.tools import BaseTool
import json

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class SupabaseLoggerTool(BaseTool):
    name: str = "Log Interaction"
    description: str = "Logs an interaction or action taken by the agent into Supabase for monitoring. Provide agent_name, action, and metadata (json-like string)."

    def _run(self, agent_name: str, action: str, metadata: str) -> str:
        try:
            data = {
                "agent_name": agent_name,
                "action": action,
                "metadata": json.loads(metadata) if isinstance(metadata, str) else metadata
            }
            # Nota: Asumiendo que la tabla se llama 'interaction_logs' como en el plan
            res = supabase.table("interaction_logs").insert(data).execute()
            return "Action logged successfully in Supabase."
        except Exception as e:
            return f"Error logging in Supabase: {str(e)}"

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
