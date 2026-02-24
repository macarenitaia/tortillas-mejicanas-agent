from crewai import Agent, Task, Crew, Process
from tools_odoo import OdooSearchTool, OdooLeadTool, OdooCalendarTool
from tools_rag import OdooRAGTool
from tools_supabase import SupabaseLoggerTool, SupabaseMemoryTool
from langchain_openai import ChatOpenAI
import os
from config import OPENAI_API_KEY

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

# --- Agentes ---

support_agent = Agent(
    role='Especialista en Soporte Técnico',
    goal='Responder dudas de los clientes basándose ÚNICAMENTE en la documentación proporcionada y el historial del cliente.',
    backstory='Eres un experto en el producto con acceso a manuales detallados. Tu prioridad es la precisión y no inventar información.',
    tools=[OdooRAGTool(), SupabaseMemoryTool(), SupabaseLoggerTool()],
    llm=llm,
    verbose=True
)

sales_agent = Agent(
    role='Ejecutivo de Ventas y CRM',
    goal='Identificar oportunidades, calificar leads y registrar toda la información relevante en Odoo.',
    backstory='Eres un cerrador experto pero amable. Te aseguras de que cada cliente potencial esté correctamente registrado en Odoo y de agendar una reunión si el lead es de alta calidad.',
    tools=[OdooSearchTool(), OdooLeadTool(), OdooCalendarTool(), SupabaseLoggerTool()],
    llm=llm,
    verbose=True
)

# --- Tareas ---

def create_tasks(session_id, user_message, customer_context=""):
    
    identify_task = Task(
        description=f"1. Identificar si el cliente con el mensaje '{user_message}' ya existe en Odoo usando su número (si está disponible en el metadato de sesión).\n"
                    f"2. Recuperar el historial de Supabase para la sesión {session_id}.\n"
                    f"3. Decidir si la consulta es de Soporte o de Ventas.",
        expected_output="Un informe detallado sobre la identidad del cliente, su historial relevante y la clasificación de su intención.",
        agent=sales_agent
    )

    action_task = Task(
        description=f"Basado en la intención identificada:\n"
                    f"- Si es Soporte: Responder la duda usando RAG.\n"
                    f"- Si es Ventas: Calificar al lead, pedir datos faltantes si es necesario, y si está listo, crear el lead en Odoo y agendar una reunión.\n"
                    f"Mensaje actual: {user_message}",
        expected_output="Respuesta final al usuario y confirmación de acciones realizadas en Odoo/Supabase.",
        agent=sales_agent,
        context=[identify_task]
    )
    
    return [identify_task, action_task]

# --- Crew ---

def run_odoo_crew(session_id, user_message):
    tasks = create_tasks(session_id, user_message)
    crew = Crew(
        agents=[support_agent, sales_agent],
        tasks=tasks,
        process=Process.sequential,
        verbose=True
    )
    return crew.kickoff()
