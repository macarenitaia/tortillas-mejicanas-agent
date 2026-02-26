from crewai import Agent, Task, Crew, Process
from tools_odoo import OdooSearchTool, OdooCheckAvailabilityTool, OdooFullBookingTool, odoo
from tools_email import SendEmailTool
from tools_rag import OdooRAGTool
from tools_supabase import SupabaseMemoryTool, save_message, get_recent_messages
from langchain_openai import ChatOpenAI
from logger import get_logger
import os
from config import OPENAI_API_KEY, OPENAI_MODEL_NAME
from datetime import datetime
import pytz

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

log = get_logger("crew_logic")
llm = ChatOpenAI(model=OPENAI_MODEL_NAME, api_key=OPENAI_API_KEY)

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
    goal='Atender de manera amigable y conversacional. Resolver dudas primero. Si el usuario EXPLÍCITAMENTE pide reunión, recabar datos sutilmente y agendar.',
    backstory='Te llamas Sofía y eres la asistente de Real to Digital.\n'
              'REGLA 1 (SALUDO): Si el contexto CRM dice que el usuario YA EXISTE, salúdalo directamente por su nombre con confianza ("¡Hola [nombre]!"). Si es nuevo, preséntate: "Hola soy Sofía, tu asistente de Real to Digital, ¿en qué puedo ayudarte?".\n'
              'REGLA 2 (NATURALIDAD): Resuelve primero la consulta del cliente. Mantén un tono muy cálido y humano.\n'
              'REGLA 3 (AGENDAR): Solo cuando el usuario PIDA EXPLÍCITAMENTE una reunión, empieza a recabar datos. Si ya tienes su nombre, email y teléfono del CRM, NO los pidas de nuevo.\n'
              'REGLA 4 (ODOO UTC): Odoo requiere la hora en UTC. Para España (CET/CEST), resta 1h en invierno o 2h en verano.\n'
              'REGLA 5 (HERRAMIENTAS): NUNCA asumas que una reunión está agendada si no has ejecutado OdooFullBookingTool con éxito.\n'
              'REGLA 6 (EMAIL): Después de agendar UNA REUNIÓN CON ÉXITO, envía un email de confirmación usando SendEmailTool.\n'
              'REGLA 7 (ANTI-ALUCINACIÓN): NUNCA inventes reuniones, citas o compromisos que NO existan. NUNCA asumas lo que el usuario quiere. Si dice "hola", simplemente responde al saludo. NO menciones reuniones anteriores a menos que el usuario las mencione PRIMERO. NO agendes nada que el usuario NO haya pedido EXPLÍCITAMENTE en ESTE mensaje.\n' + REGLAS_WHATSAPP,
    tools=[OdooSearchTool(), OdooCheckAvailabilityTool(), OdooFullBookingTool(), SendEmailTool()],
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

def run_odoo_crew(session_id: str, user_message: str) -> str:
    try:
        log.info(f"[STEP 1/6] Saving user message for session {session_id[:8]}***")
        save_message(session_id, "usuario", user_message)
        
        log.info("[STEP 2/6] Fetching chat history")
        chat_history = get_recent_messages(session_id, limit=6)
        
        log.info("[STEP 3/6] Searching partner in Odoo")
        try:
            partner = odoo.search_partner_by_phone(session_id)
        except Exception as odoo_err:
            log.warning(f"Odoo search_partner failed (non-fatal): {type(odoo_err).__name__}: {odoo_err}")
            partner = None
            
        if partner:
            p_name = partner['name']
            p_email = partner.get('email', '')
            p_phone = partner.get('phone', '') or partner.get('mobile', '')
            crm_context = (
                f"IDENTIDAD CONFIRMADA DEL USUARIO (datos del CRM, son 100% fiables):\n"
                f"- Nombre: {p_name}\n"
                f"- Email: {p_email}\n"
                f"- Teléfono: {p_phone}\n"
                f"INSTRUCCIÓN: Este usuario es un CLIENTE CONOCIDO. Llámalo '{p_name}' con total seguridad. "
                f"NO le preguntes su nombre, NO le preguntes su email, NO le pidas confirmar quién es. "
                f"YA TIENES TODOS SUS DATOS. Si pide agendar reunión, usa directamente estos datos."
            )
        else:
            crm_context = "El usuario es NUEVO, no está en nuestro CRM. Salúdalo cálidamente. Cuando sea necesario, averigua su nombre de forma natural."

        log.info("[STEP 4/6] Creating CrewAI tasks")
        tasks = create_tasks(session_id, user_message, chat_history, crm_context)
        crew = Crew(
            agents=[support_agent, sales_agent],
            tasks=tasks,
            process=Process.sequential,
            verbose=True
        )
        
        log.info("[STEP 5/6] Executing crew.kickoff()")
        result = crew.kickoff()
        final_text = str(result)
        
        log.info("[STEP 6/6] Saving agent response")
        save_message(session_id, "agente", final_text)
        
        log.info(f"Crew completed. Response length: {len(final_text)} chars")
        return final_text
    except Exception as e:
        import traceback
        log.error(f"run_odoo_crew crash: {traceback.format_exc()}")
        return "Disculpa, estoy experimentando dificultades técnicas. Por favor, inténtalo de nuevo en unos minutos. 🙏"
