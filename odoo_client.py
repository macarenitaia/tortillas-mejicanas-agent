import xmlrpc.client
import time
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, ODOO_API_KEY

class OdooClient:
    def __init__(self):
        self.url = ODOO_URL
        self.db = ODOO_DB
        self.username = ODOO_USERNAME
        self.password = ODOO_API_KEY if ODOO_API_KEY else ODOO_PASSWORD
        self.uid = None

    def _ensure_authenticated(self):
        if not self.uid:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            
            # Probar API Key primero, si falla probar Password normal
            passwords_to_try = []
            if ODOO_API_KEY:
                passwords_to_try.append(ODOO_API_KEY)
            if ODOO_PASSWORD and ODOO_PASSWORD not in passwords_to_try:
                passwords_to_try.append(ODOO_PASSWORD)
            
            if not passwords_to_try:
                passwords_to_try.append("") # Fallback vacío
                
            for test_pwd in passwords_to_try:
                for attempt in range(3):
                    try:
                        uid = common.authenticate(self.db, self.username, test_pwd, {})
                        if uid:
                            self.uid = uid
                            self.password = test_pwd # Confirmar la contraseña ganadora para el resto de métodos
                            return # Autenticación Exitosa
                        break # Si devuelve False sin excepción, es credencial inválida, salir del retry (429) e intentar siguiente passwd
                    except xmlrpc.client.ProtocolError as e:
                        if e.errcode == 429 and attempt < 2:
                            time.sleep(2 ** attempt)
                        else:
                            raise
            
            # Si termina el bucle y seguimos sin UID, entonces ninguna funcionó
            if not self.uid:
                raise Exception("Odoo authentication failed. Credenciales XML-RPC inválidas (ni API KEY ni PASS funcionan).")

    def _get_models(self):
        self._ensure_authenticated()
        return xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def _execute_kw_with_retry(self, model, method, *args, **kwargs):
        """Ejecuta llamadas a Odoo XML-RPC con reintento y espera en caso de Rate Limiting (429)."""
        models = self._get_models()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return models.execute_kw(self.db, self.uid, self.password, model, method, *args, **kwargs)
            except xmlrpc.client.ProtocolError as e:
                if e.errcode == 429 and attempt < max_retries - 1:
                    wait_time = 2 ** attempt # Exponential backoff: 1s, 2s
                    print(f"[Odoo API] Límite alcanzado (429). Reintentando en {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

    def search_partner_by_phone(self, phone):
        """Busca un partner por teléfono o móvil."""
        # Limpiar el teléfono para la búsqueda (solo dígitos)
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        domain = [
            '|', 
            ('phone', 'ilike', clean_phone), 
            ('mobile', 'ilike', clean_phone)
        ]
        
        partner_ids = self._execute_kw_with_retry('res.partner', 'search', [domain])
        
        if partner_ids:
            partners = self._execute_kw_with_retry('res.partner', 'read', [partner_ids], {'fields': ['name', 'email', 'phone', 'mobile']})
            return partners[0]
        return None

    def create_lead(self, name, phone, email=None, description=None):
        """Crea un lead en el CRM."""
        vals = {
            'name': name,
            'phone': phone,
            'email_from': email,
            'description': description,
            'type': 'opportunity'
        }
        lead_id = self._execute_kw_with_retry('crm.lead', 'create', [vals])
        return lead_id

    def schedule_meeting(self, partner_id, summary, start_date, duration=1.0):
        """Agenda un evento en el calendario."""
        vals = {
            'name': summary,
            'start': start_date, # Formato: 'YYYY-MM-DD HH:MM:SS'
            'stop': start_date, # Odoo suele requerir datetime real, simplificamos asumiendo start=stop o suma
            'duration': duration,
            'partner_ids': [(4, partner_id)]
        }
        event_id = self._execute_kw_with_retry('calendar.event', 'create', [vals])
        return event_id

    def check_availability(self, date_start, date_end):
        """Lee el calendario de Odoo entre dos fechas y devuelve los eventos ocupados."""
        # Buscar eventos que se solapen con el rango dado
        domain = [
            ('start', '<', date_end),
            ('stop', '>', date_start)
        ]
        # Recuperar eventos (nombre y horas)
        event_ids = self._execute_kw_with_retry('calendar.event', 'search', [domain])
        if event_ids:
            events = self._execute_kw_with_retry('calendar.event', 'read', [event_ids], {'fields': ['name', 'start', 'stop']})
            return events
        return []

    def create_full_booking(self, name, phone, email, description, start_date, duration=1.0):
        """Crea el ecosistema completo: Partner -> Lead -> Event, asegurando la clave foránea."""
        
        # 1. Crear Contacto (Partner)
        partner_id = self._execute_kw_with_retry('res.partner', 'create', [{
            'name': name,
            'phone': phone,
            'email': email
        }])

        # 2. Crear Oportunidad (Lead) vinculada al Partner
        lead_id = self._execute_kw_with_retry('crm.lead', 'create', [{
            'name': f"Oportunidad de {name}",
            'partner_id': partner_id,
            'description': description,
            'type': 'opportunity'
        }])

        # 3. Crear Evento en Calendario (Meeting) vinculado al Partner y Lead
        event_id = self._execute_kw_with_retry('calendar.event', 'create', [{
            'name': f"Reunión Comercial: {name}",
            'start': start_date,
            'stop': start_date, # Simplificación temporal
            'duration': duration,
            'partner_ids': [(4, partner_id)], # Asociar al cliente
            'opportunity_id': lead_id # Asociar a la oportunidad directamente
        }])

        return {
            'partner_id': partner_id,
            'lead_id': lead_id,
            'event_id': event_id
        }
