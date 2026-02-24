from openai import OpenAI
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY
from crewai.tools import BaseTool
import json

client = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class OdooRAGTool(BaseTool):
    name: str = "Knowledge Base Search"
    description: str = "Searches the company knowledge base for technical information, services, and pricing of Real to Digital. Use this for ANY question about what the company does."

    def _run(self, query: str) -> str:
        try:
            # 1. Generar embedding para la consulta
            response = client.embeddings.create(
                input=query,
                model="text-embedding-3-small"
            )
            query_embedding = response.data[0].embedding

            # 2. Llamar a la función RPC de Supabase para búsqueda por similitud
            # Nota: El nombre de la función 'match_kb_items' o 'match_documents' debe existir en Supabase
            # Según el esquema visto, es 'match_kb_items'
            rpc_params = {
                "query_embedding": query_embedding,
                "match_threshold": 0.5,
                "match_count": 5,
                "p_agent_id": None # Buscamos en toda la organización si no hay ID específico
            }
            
            res = supabase.rpc("match_kb_items", rpc_params).execute()
            
            if not res.data:
                return "No se encontró información relevante en la base de conocimientos."
            
            context = "Información encontrada:\n"
            for item in res.data:
                context += f"- {item['content']}\n"
            
            return context
        except Exception as e:
            return f"Error en la búsqueda RAG: {str(e)}"
