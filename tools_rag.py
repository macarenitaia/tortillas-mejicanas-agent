"""
Herramienta RAG para búsqueda semántica en la base de conocimientos de Tortillas Mejicanas.
Reutiliza el cliente Supabase global de tools_supabase para evitar duplicación.
"""
from openai import OpenAI
from crewai.tools import BaseTool
from config import OPENAI_API_KEY
from logger import get_logger

log = get_logger("tools_rag")

# Cliente OpenAI para embeddings
_openai_client = OpenAI(api_key=OPENAI_API_KEY)


class OdooRAGTool(BaseTool):
    """Busca en la base de conocimientos de Tortillas Mejicanas usando búsqueda semántica."""
    name: str = "Knowledge Base Search"
    description: str = "Searches the company knowledge base for product information, services, and pricing of Tortillas Mejicanas. Use this for ANY question about products, prices, or what the company offers."

    def _run(self, query: str) -> str:
        try:
            # Importar el cliente Supabase de tools_supabase (lazy, evita crash al import)
            from tools_supabase import supabase
            
            # 1. Generar embedding para la consulta
            response = _openai_client.embeddings.create(
                input=query,
                model="text-embedding-3-small"
            )
            query_embedding = response.data[0].embedding

            # 2. Búsqueda por similitud via RPC
            rpc_params = {
                "query_embedding": query_embedding,
                "match_threshold": 0.5,
                "match_count": 5,
                "p_agent_id": None
            }
            
            res = supabase.rpc("match_kb_items", rpc_params).execute()
            
            if not res.data:
                return "No se encontró información relevante en la base de conocimientos."
            
            context = "Información encontrada:\n"
            for item in res.data:
                context += f"- {item['content']}\n"
            
            return context
        except Exception as e:
            log.error(f"RAG search error: {type(e).__name__}")
            return "No se pudo consultar la base de conocimientos en este momento."
