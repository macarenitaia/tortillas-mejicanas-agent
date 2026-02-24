import xmlrpc.client
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
            self.uid = common.authenticate(self.db, self.username, self.password, {})
            if not self.uid:
                raise Exception("Odoo authentication failed.")

    def _get_models(self):
        self._ensure_authenticated()
        return xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def search_partner_by_phone(self, phone):
        """Busca un partner por teléfono o móvil."""
        models = self._get_models()
        # Limpiar el teléfono para la búsqueda (solo dígitos)
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        domain = [
            '|', 
            ('phone', 'ilike', clean_phone), 
            ('mobile', 'ilike', clean_phone)
        ]
        
        partner_ids = models.execute_kw(self.db, self.uid, self.password, 'res.partner', 'search', [domain])
        
        if partner_ids:
            partners = models.execute_kw(self.db, self.uid, self.password, 'res.partner', 'read', [partner_ids], {'fields': ['name', 'email', 'phone', 'mobile']})
            return partners[0]
        return None

    def create_lead(self, name, phone, email=None, description=None):
        """Crea un lead en el CRM."""
        models = self._get_models()
        vals = {
            'name': name,
            'phone': phone,
            'email_from': email,
            'description': description,
            'type': 'opportunity'
        }
        lead_id = models.execute_kw(self.db, self.uid, self.password, 'crm.lead', 'create', [vals])
        return lead_id

    def schedule_meeting(self, partner_id, summary, start_date, duration=1.0):
        """Agenda un evento en el calendario."""
        models = self._get_models()
        vals = {
            'name': summary,
            'start': start_date, # Formato: 'YYYY-MM-DD HH:MM:SS'
            'stop': start_date, # Odoo suele requerir datetime real, simplificamos asumiendo start=stop o suma
            'duration': duration,
            'partner_ids': [(4, partner_id)]
        }
        event_id = models.execute_kw(self.db, self.uid, self.password, 'calendar.event', 'create', [vals])
        return event_id

    def check_availability(self, date_start, date_end):
        """Lee el calendario de Odoo entre dos fechas y devuelve los eventos ocupados."""
        models = self._get_models()
        # Buscar eventos que se solapen con el rango dado
        domain = [
            ('start', '<', date_end),
            ('stop', '>', date_start)
        ]
        # Recuperar eventos (nombre y horas)
        event_ids = models.execute_kw(self.db, self.uid, self.password, 'calendar.event', 'search', [domain])
        if event_ids:
            events = models.execute_kw(self.db, self.uid, self.password, 'calendar.event', 'read', [event_ids], {'fields': ['name', 'start', 'stop']})
            return events
        return []

    def create_full_booking(self, name, phone, email, description, start_date, duration=1.0):
        """Crea el ecosistema completo: Partner -> Lead -> Event, asegurando la clave foránea."""
        models = self._get_models()
        
        # 1. Crear Contacto (Partner)
        partner_id = models.execute_kw(self.db, self.uid, self.password, 'res.partner', 'create', [{
            'name': name,
            'phone': phone,
            'email': email
        }])

        # 2. Crear Oportunidad (Lead) vinculada al Partner
        lead_id = models.execute_kw(self.db, self.uid, self.password, 'crm.lead', 'create', [{
            'name': f"Oportunidad de {name}",
            'partner_id': partner_id,
            'description': description,
            'type': 'opportunity'
        }])

        # 3. Crear Evento en Calendario (Meeting) vinculado al Partner y Lead
        event_id = models.execute_kw(self.db, self.uid, self.password, 'calendar.event', 'create', [{
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
