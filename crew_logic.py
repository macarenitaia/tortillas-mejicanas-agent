from crewai import Agent, Task, Crew, Process
from tools_odoo import OdooSearchTool, OdooCheckAvailabilityTool, OdooFullBookingTool, odoo
from tools_rag import OdooRAGTool
from tools_supabase import SupabaseMemoryTool, save_message, get_recent_messages
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
    role='Especialista Comercial de Real to Digital',
    goal='Atender de manera amigable y conversacional. Resolver dudas primero. Si el usuario pide reunión, recabar datos sutilmente y agendar.',
    backstory='Te llamas Sofía y eres la asistente de Real to Digital.\n'
              'REGLA 1 (SALUDO INICIAL): En el primer contacto, preséntate EXACTAMENTE así y luego conversa de forma natural: "Hola soy Sofía, tu asistente de Real to Digital, ¿en qué puedo ayudarte?". NO PIDAS NINGÚN DATO TOdAVÍA.\n'
              'REGLA 2 (NATURALIDAD): Resuelve primero la consulta del cliente. Mantén un tono muy cálido y humano.\n'
              'REGLA 3 (AGENDAR): Solo cuando quiera reunirse, empieza a pedir sus datos (Nombre, Email, Teléfono y Empresa) de forma MUY sutil, uno a uno, integrándolo en tu charla.\n'
              'REGLA 4 (ODOO UTC): Odoo requiere la hora de tus herramientas estrictamente en UTC. Debes restar el desfase de Madrid antes de introducirla en el código.\n'
              'REGLA 5 (HERRAMIENTAS): NUNCA asumas que una reunión está agendada si no has ejecutado OdooFullBookingTool con éxito.\n' + REGLAS_WHATSAPP,
    tools=[OdooSearchTool(), OdooCheckAvailabilityTool(), OdooFullBookingTool()],
    llm=llm,
    verbose=True
)

# --- Tareas ---

def create_tasks(session_id, user_message, chat_history="", crm_context=""):
    
    # Contexto Temporal con soporte UTC
    tz = pytz.timezone('Europe/Madrid')
    now = datetime.now(tz)
    offset_hours = int(now.utcoffset().total_seconds() / 3600)
    date_context = (f"Hoy es {now.strftime('%A, %d de %B de %Y, hora local %H:%M')}. "
                    f"IMPORTANTE: Odoo exige que envíes las horas a sus herramientas en formato UTC. "
                    f"Madrid tiene un desfase horario de +{offset_hours} horas. "
                    f"Por lo tanto, la hora que envíes a la herramienta debe restarle {offset_hours} horas a la hora acordada con el cliente (Ej. si el cliente dice 11:00 am, envía a las {11 - offset_hours:02d}:00:00).")

    identify_task = Task(
        description=f"Analiza si debemos orientar la conversación a Soporte o Comercial.\n"
                    f"NOTA TEMPORAL IMPORTANTE: {date_context}\n\n"
                    f"--- ESTADO DEL CLIENTE EN CRM ---\n{crm_context}\n\n"
                    f"--- HISTORIAL DE LA CONVERSACIÓN ---\n{chat_history}\n-----------------------------------\n"
                    f"El último mensaje del usuario es: '{user_message}'",
        expected_output="Un informe detallado sobre la identidad del cliente, los datos que YA ha proporcionado en el historial, y la clasificación de su intención.",
        agent=sales_agent
    )

    action_task = Task(
        description=f"Basado en la intención identificada sigue este FLUJO NATURAL (Tú eres Sofía):\n"
                    f"1. Si el usuario es nuevo, saluda y pregúntale en qué puedes ayudar.\n"
                    f"2. Si es una duda, resuelve su consulta de forma amable y cálida.\n"
                    f"3. Si muestra interés en cerrar una reunión y aún no tienes todos sus datos claves (Nombre, Email, Teléfono), comiénzaselos a pedir muy sutilmente insertándolos en la plática, no de golpe.\n"
                    f"4. Si ya tienes los datos y propone una cita:\n"
                    f"    a) Valida la hora con OdooCheckAvailabilityTool (RECUERDA RESTAR {offset_hours} HORAS PARA UTC ANTES DE LLAMARLA).\n"
                    f"    b) Si está ocupado, proponle otro rango horario amable.\n"
                    f"    c) Si está libre, cierra el trato con OdooFullBookingTool (restando {offset_hours} horas para el formato de entrada UTC).\n"
                    f"Mensaje actual del cliente: {user_message}",
        expected_output="Responder a la duda, solicitar un dato faltante o agendar de la manera más humana posible, como una Asistente muy dulce de la empresa.",
        agent=sales_agent,
        context=[identify_task]
    )
    
    return [identify_task, action_task]

# --- Crew ---

def run_odoo_crew(session_id, user_message):
    try:
        # 1. Guardar el mensaje del usuario en memoria a largo plazo
        save_message(session_id, "usuario", user_message)
        
        # 2. Recuperar el historial reciente
        chat_history = get_recent_messages(session_id, limit=6)
        
        # 3. Buscar proactivamente al cliente en Odoo para darle contexto a la IA
        partner = odoo.search_partner_by_phone(session_id)
        if partner:
            crm_context = f"El usuario actual YA EXISTE en nuestro CRM de Odoo. Su nombre es: {partner['name']}, y su email es: {partner.get('email', 'N/A')}. Llámalo por su nombre para darle un trato VIP y NO le pidas su email ni nombre de nuevo."
        else:
            crm_context = "El usuario es NUEVO, no sabemos ni su nombre ni nada. Salúdalo cálidamente y cuando sea el momento sutil, averigua cómo se llama."

        # 4. Formular la tarea con el historial e identidad inyectados
        tasks = create_tasks(session_id, user_message, chat_history, crm_context)
        crew = Crew(
            agents=[support_agent, sales_agent],
            tasks=tasks,
            process=Process.sequential,
            verbose=True
        )
        
        # 5. Ejecutar la inteligencia y obtener respuesta
        result = crew.kickoff()
        final_text = str(result)
        
        # 6. Guardar la respuesta definitiva del agente en memoria
        save_message(session_id, "agente", final_text)
        
        return final_text
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"CRASH IN RUN_ODOO_CREW: {error_details}")
        return f"Error técnico interno del Agente. Info para el dev: {str(e)}"
