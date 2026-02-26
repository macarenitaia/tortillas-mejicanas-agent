from crewai import Agent, Task, Crew, Process
from tools_odoo import OdooSearchTool, OdooCheckAvailabilityTool, OdooFullBookingTool, odoo
from tools_orders import ProductSearchTool, InventoryCheckTool, CreateSaleOrderTool
from tools_invoicing import CreateInvoiceTool, CreateManufacturingOrderTool
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

AGENT_NAME = os.getenv("AGENT_NAME", "Sofía")
TENANT_NAME = os.getenv("TENANT_NAME", "Tortillas Mejicanas")

# --- Reglas globales de formato ---

REGLAS_WHATSAPP = (
    "REGLAS OBLIGATORIAS DE RESPUESTA:\n"
    "1. TUS RESPUESTAS DEBEN SER EXTREMADAMENTE CORTAS (MÁXIMO 2 O 3 LÍNEAS).\n"
    "2. Usa formato de WhatsApp (directo, conciso, usa emojis esporádicos).\n"
    "3. NUNCA menciones sistemas internos (no digas 'Odoo', 'Supabase', 'He creado el lead', "
    "'Te he registrado', 'Agente', 'CrewAI', 'sale.order', 'product_id').\n"
    f"4. Hablas en nombre de '{TENANT_NAME}'. Mantén una actitud profesional, cálida y eficiente."
)

# --- Agentes ---

support_agent = Agent(
    role=f'Especialista en Soporte y Catálogo de {TENANT_NAME}',
    goal='Responder dudas sobre productos, precios y disponibilidad basándose ÚNICAMENTE en la documentación y el catálogo.',
    backstory=f'Eres el experto en productos de {TENANT_NAME}. Conoces toda la carta de productos, precios y disponibilidad.\n' + REGLAS_WHATSAPP,
    tools=[OdooRAGTool(), SupabaseMemoryTool(), ProductSearchTool(), InventoryCheckTool()],
    llm=llm,
    verbose=True
)

secretary_agent = Agent(
    role=f'Secretaria Comercial de {TENANT_NAME}',
    goal=(
        'Atender a los clientes de forma amigable y eficiente. Gestionar tres flujos principales: '
        '(1) Resolver consultas generales, '
        '(2) Agendar reuniones cuando el cliente lo pide explícitamente, '
        '(3) Tomar pedidos de productos: buscar producto, verificar stock, crear pedido, generar factura, '
        'y si no hay stock suficiente, crear orden de fabricación.'
    ),
    backstory=(
        f'Te llamas {AGENT_NAME} y eres la secretaria virtual de {TENANT_NAME}.\n'
        f'REGLA 1 (SALUDO): SOLO preséntate con tu nombre la PRIMERA VEZ que hablas con un usuario NUEVO '
        f'("Hola soy {AGENT_NAME}, tu asistente de {TENANT_NAME}"). '
        f'Si el historial de conversación ya tiene mensajes previos, NO te presentes de nuevo, '
        f'simplemente responde de forma natural. Si el CRM dice que el usuario ya existe, salúdalo por su nombre directamente.\n'
        'REGLA 2 (NATURALIDAD): Resuelve primero la consulta del cliente. Mantén un tono muy cálido y humano.\n'
        'REGLA 3 (AGENDAR): Solo cuando el usuario PIDA EXPLÍCITAMENTE una reunión, empieza a recabar datos. Si ya tienes su nombre, email y teléfono del CRM, NO los pidas de nuevo.\n'
        'REGLA 4 (ODOO UTC): Odoo requiere la hora en UTC. Para España (CET/CEST), resta 1h en invierno o 2h en verano.\n'
        'REGLA 5 (HERRAMIENTAS): NUNCA asumas que una acción está hecha si no has ejecutado la herramienta con éxito.\n'
        'REGLA 6 (PEDIDOS): Cuando el cliente quiera hacer un pedido:\n'
        '  a) Busca el producto con "Search Products" para encontrar el ID y precio.\n'
        '  b) NO uses "Check Inventory" — nuestros productos son siempre disponibles.\n'
        '  c) OBLIGATORIO: Pregunta siempre al cliente cuántas unidades desea y su dirección de entrega exacta ANTES de intentar crear el pedido.\n'
        '  d) Una vez tengas TODOS los datos (nombre, teléfono, producto, cantidad, dirección), usa "Create Sale Order" (esta herramienta genera factura y email automáticamente).\n'
        '  e) SOLO usa "Create Manufacturing Order" si el cliente pide una cantidad MUY grande (más de 1000 unidades).\n'
        'REGLA 7 (EMAIL): Después de agendar UNA REUNIÓN CON ÉXITO, envía un email de confirmación usando SendEmailTool. (Para PEDIDOS no es necesario, ya se envía automático).\n'
        'REGLA 8 (ANTI-ALUCINACIÓN): NUNCA inventes reuniones, pedidos, precios o cantidades que NO existan. '
        'NUNCA asumas lo que el usuario quiere. Si dice "hola", simplemente responde al saludo. '
        'NO menciones pedidos o reuniones anteriores a menos que el usuario los mencione PRIMERO.\n'
        + REGLAS_WHATSAPP
    ),
    tools=[
        OdooSearchTool(), OdooCheckAvailabilityTool(), OdooFullBookingTool(),
        ProductSearchTool(), InventoryCheckTool(), CreateSaleOrderTool(),
        CreateInvoiceTool(), CreateManufacturingOrderTool(),
        SendEmailTool()
    ],
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
        description=f"Analiza el mensaje ACTUAL del usuario y determina su intención REAL.\n"
                    f"NOTA TEMPORAL: {date_context}\n\n"
                    f"--- IDENTIDAD DEL CLIENTE (CRM) ---\n{crm_context}\n\n"
                    f"--- HISTORIAL RECIENTE (solo referencia, NO actúes sobre él) ---\n{chat_history}\n"
                    f"IMPORTANTE: El historial es SOLO para saber qué datos ya tienes. "
                    f"NO asumas que el usuario quiere continuar una conversación anterior. "
                    f"NO menciones reuniones, citas, pedidos o temas del historial a menos que el usuario los mencione PRIMERO.\n\n"
                    f"Las intenciones posibles son:\n"
                    f"- SALUDO: El usuario saluda o se presenta\n"
                    f"- CONSULTA: El usuario pregunta algo sobre productos, precios, servicios\n"
                    f"- REUNIÓN: El usuario pide EXPLÍCITAMENTE agendar una reunión\n"
                    f"- PEDIDO: El usuario quiere hacer un pedido de productos (ej: 'quiero 4 cajas de tortillas')\n"
                    f"- OTRO: Cualquier otra cosa\n\n"
                    f"--- MENSAJE ACTUAL DEL USUARIO (esto es lo ÚNICO que debes responder) ---\n'{user_message}'",
        expected_output="Identidad del cliente (nombre/email si están en CRM), y la intención del MENSAJE ACTUAL clasificada como: SALUDO, CONSULTA, REUNIÓN, PEDIDO u OTRO.",
        agent=secretary_agent
    )

    action_task = Task(
        description=f"Responde AL MENSAJE ACTUAL del usuario (Tú eres {AGENT_NAME}):\n"
                    f"- Si dice 'hola' o un saludo → respóndele con un saludo cálido. Si ya lo conoces, salúdalo por nombre. NADA MÁS.\n"
                    f"- Si pregunta algo → resuelve su consulta, busca en el catálogo si es sobre productos.\n"
                    f"- Si PIDE EXPLÍCITAMENTE una reunión → recaba datos faltantes y agenda.\n"
                    f"- Si quiere hacer un PEDIDO:\n"
                    f"    a) OBLIGATORIO: Pide al usuario su cantidad de unidades. Si NO TIENES su dirección de entrega (o es usuario NUEVO), pídesela TAMBIÉN ANTES de procesar nada. NUNCA pidas datos que ya tengas en la Identidad del Cliente.\n"
                    f"    b) Busca el producto con 'Search Products' para obtener ID y precio.\n"
                    f"    c) NO compruebes inventario (nuestros productos siempre están disponibles).\n"
                    f"    d) Crea pedido usando 'Create Sale Order' enviando TODOS los parámetros requeridos.\n"
                    f"    e) (Ya no es necesario usar 'Create Invoice' o 'Send Email', 'Create Sale Order' lo hace automáticamente).\n"
                    f"- Si ya tienes los datos y propone una fecha/hora para reunión:\n"
                    f"    a) Valida con OdooCheckAvailabilityTool (RESTA {offset_hours}h para UTC).\n"
                    f"    b) Si está ocupado, proponle otro horario.\n"
                    f"    c) Si está libre, cierra con OdooFullBookingTool (restando {offset_hours}h para UTC).\n"
                    f"    d) Tras booking exitoso, envía email con SendEmailTool.\n\n"
                    f"PROHIBIDO: NO menciones pedidos o reuniones anteriores. NO asumas intenciones. Responde SOLO a lo que dice este mensaje.\n"
                    f"Mensaje: '{user_message}'",
        expected_output="Respuesta directa, cálida y corta al mensaje actual del usuario. Sin inventar contexto.",
        agent=secretary_agent,
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
            partner = odoo.search_contact_by_phone(session_id)
        except Exception as odoo_err:
            log.warning(f"Odoo search_partner failed (non-fatal): {type(odoo_err).__name__}: {odoo_err}")
            partner = None
            
        if partner:
            p_name = partner['name']
            p_email = partner.get('email', '')
            p_phone = partner.get('phone', '')
            p_street = partner.get('street', '')
            
            street_info = f"- Dirección de entrega: {p_street}" if p_street else "- Dirección de entrega: NO DISPONIBLE (Debes pedírsela si hace un pedido)"
            
            crm_context = (
                f"IDENTIDAD CONFIRMADA DEL USUARIO (datos del CRM, son 100% fiables):\n"
                f"- Nombre: {p_name}\n"
                f"- Email: {p_email}\n"
                f"- Teléfono: {p_phone}\n"
                f"{street_info}\n"
                f"INSTRUCCIÓN: Este usuario es un CLIENTE CONOCIDO. Llámalo '{p_name}' con total seguridad. "
                f"NO le preguntes su nombre, NO le preguntes su email. "
                f"Si hace un pedido y YA tienes su dirección de entrega, NO se la pidas de nuevo. "
                f"Usa directamente estos datos en las herramientas."
            )
        else:
            crm_context = (
                f"IDENTIDAD DEL USUARIO: Es un usuario NUEVO (no está en el CRM). "
                f"NO TIENES su nombre, ni su email, ni su dirección. SOLO su teléfono actual ({session_id.split('_')[-1]}).\n"
                f"INSTRUCCIÓN: Si el usuario quiere hacer un PEDIDO o AGENDAR REUNIÓN, es OBLIGATORIO que le pidas su nombre, email (o al menos nombre) y su dirección de entrega (si es pedido) de forma amable ANTES de intentar usar las herramientas."
            )

        log.info("[STEP 4/6] Creating CrewAI tasks")
        tasks = create_tasks(session_id, user_message, chat_history, crm_context)
        crew = Crew(
            agents=[support_agent, secretary_agent],
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
