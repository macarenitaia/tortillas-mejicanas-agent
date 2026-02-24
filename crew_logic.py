from crewai import Agent, Task, Crew, Process
from tools_odoo import OdooSearchTool, OdooLeadTool, OdooCalendarTool
from tools_rag import OdooRAGTool
from tools_supabase import SupabaseMemoryTool
from langchain_openai import ChatOpenAI
import os
from config import OPENAI_API_KEY
from datetime import datetime
import pytz

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY)

# --- Agentes ---

REGLAS_WHATSAPP = (
    "REGLAS OBLIGATORIAS DE RESPUESTA:\n"
    "1. TUS RESPUESTAS DEBEN SER EXTREMADAMENTE CORTAS (MÁXIMO 2 O 3 LÍNEAS).\n"
    "2. Usa formato de WhatsApp (directo, conciso, usa emojis esporádicos).\n"
    "3. NUNCA menciones sistemas internos (no digas 'Odoo', 'Supabase', 'He creado el lead', 'Te he registrado', 'Agente', 'CrewAI').\n"
    "4. Hablas en nombre de 'Real to Digital'. Mantén una actitud comercial, amable y persuasiva."
)

support_agent = Agent(
    role='Especialista en Soporte Técnico de Real to Digital',
    goal='Responder dudas de los clientes basándose ÚNICAMENTE en la documentación proporcionada y el historial.',
    backstory='Eres el experto técnico de Real to Digital. Resuelves dudas rápido y al grano.\n' + REGLAS_WHATSAPP,
    tools=[OdooRAGTool(), SupabaseMemoryTool()],
    llm=llm,
    verbose=True
)

sales_agent = Agent(
    role='Ejecutivo de Ventas de Real to Digital',
    goal='Identificar oportunidades, calificar clientes y agendarlos sutilmente recabando datos sin parecer un robot.',
    backstory='Eres el mejor cerrador comercial de Real to Digital. Eres carismático y vas al grano para agendar reuniones.\n'
              'REGLA CRÍTICA DE DATOS: NUNCA ASUMAS QUE UNA REUNIÓN ESTÁ AGENDADA O UN LEAD ESTÁ CREADO SI TÚ NO HAS EJECUTADO LA HERRAMIENTA CORRESPONDIENTE.\n'
              'Para agendar, es OBLIGATORIO tener: Nombre, Email, Teléfono, Empresa (opcional) y Motivo de consulta.\n'
              'Si faltan datos, PREGUNTA AL CLIENTE sutilmente ANTES de invocar las herramientas.\n' + REGLAS_WHATSAPP,
    tools=[OdooSearchTool(), OdooLeadTool(), OdooCalendarTool()],
    llm=llm,
    verbose=True
)

# --- Tareas ---

def create_tasks(session_id, user_message, customer_context=""):
    
    # Contexto Temporal
    tz = pytz.timezone('Europe/Madrid')
    now = datetime.now(tz)
    date_context = f"Hoy es {now.strftime('%A, %d de %B de %Y, %H:%M')}. Ten muy en cuenta esta fecha y hora si el cliente te pide referencias temporales (ej. 'mañana', 'el próximo lunes') para calcular la fecha exacta para Odoo."

    identify_task = Task(
        description=f"1. Identificar si el cliente con el mensaje '{user_message}' ya existe en Odoo usando su número (si está disponible en el metadato de sesión).\n"
                    f"2. Recuperar el historial de Supabase para la sesión {session_id}.\n"
                    f"3. Decidir si la consulta es de Soporte o de Ventas.\n"
                    f"NOTA TEMPORAL IMPORTANTE: {date_context}",
        expected_output="Un informe detallado sobre la identidad del cliente, su historial relevante y la clasificación de su intención.",
        agent=sales_agent
    )

    action_task = Task(
        description=f"Basado en la intención identificada actúa según estas REGLAS ESTRICTAS:\n"
                    f"- Si es Soporte: Responder la duda usando la Tool RAG.\n"
                    f"- Si es Ventas, sigue este FLUJO EXACTO:\n"
                    f"  1. ¿Tienes AHORA MISMO el Nombre, Email, Teléfono, Empresa(opcional) y Consulta del usuario?\n"
                    f"  2. SI NO LOS TIENES TODOS: Escribe al usuario pidiéndole amablemente los datos que faltan.\n"
                    f"  3. SI LOS TIENES TODOS: \n"
                    f"      a) Ejecuta la herramienta OdooLeadTool para crear la oportunidad.\n"
                    f"      b) Escribe al usuario proponiendo una fecha.\n"
                    f"      c) Si el usuario aceptó una fecha concreta, ejecuta OdooCalendarTool.\n"
                    f"Mensaje actual del cliente: {user_message}",
        expected_output="Una acción ejecutada en las herramientas o un mensaje corto para el cliente pidiendo el siguiente dato.",
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
