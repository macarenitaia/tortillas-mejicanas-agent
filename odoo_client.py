import xmlrpc.client
import time
from typing import Optional, Dict, List, Any
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, ODOO_API_KEY
from logger import get_logger

log = get_logger("odoo_client")


def _mask_phone(phone: str) -> str:
    """Enmascara teléfono para logs."""
    if len(phone) > 4:
        return f"***{phone[-4:]}"
    return "***"


class OdooClient:
    """Cliente para Odoo XML-RPC con autenticación dual, rate-limit retry y booking transaccional."""
    
    def __init__(self) -> None:
        self.url: str = ODOO_URL
        self.db: str = ODOO_DB
        self.username: str = ODOO_USERNAME
        self.password: str = ODOO_API_KEY if ODOO_API_KEY else ODOO_PASSWORD
        self.uid: Optional[int] = None

    def _ensure_authenticated(self) -> None:
        """Autentica contra Odoo probando API Key y luego Password."""
        if self.uid:
            return
            
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        
        passwords_to_try: list = []
        if ODOO_API_KEY:
            passwords_to_try.append(ODOO_API_KEY)
        if ODOO_PASSWORD and ODOO_PASSWORD not in passwords_to_try:
            passwords_to_try.append(ODOO_PASSWORD)
        if not passwords_to_try:
            passwords_to_try.append("")
            
        for test_pwd in passwords_to_try:
            for attempt in range(3):
                try:
                    uid = common.authenticate(self.db, self.username, test_pwd, {})
                    if uid:
                        self.uid = uid
                        self.password = test_pwd
                        log.info("Odoo authenticated successfully")
                        return
                    break  # Credencial inválida, probar siguiente
                except xmlrpc.client.ProtocolError as e:
                    if e.errcode == 429 and attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        raise
        
        raise Exception("Odoo authentication failed.")

    def _get_models(self) -> xmlrpc.client.ServerProxy:
        self._ensure_authenticated()
        return xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def _execute_kw_with_retry(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Ejecuta llamadas a Odoo XML-RPC con exponential backoff."""
        models = self._get_models()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return models.execute_kw(self.db, self.uid, self.password, model, method, *args, **kwargs)
            except xmlrpc.client.ProtocolError as e:
                if e.errcode == 429 and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    log.warning(f"Odoo rate limited (429). Retry in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

    def _safe_delete(self, model: str, record_id: int) -> None:
        """Intenta eliminar un registro para compensar un booking parcial."""
        try:
            self._execute_kw_with_retry(model, 'unlink', [[record_id]])
            log.info(f"Rollback: deleted {model}:{record_id}")
        except Exception:
            log.error(f"Rollback failed: {model}:{record_id}")

    def search_partner_by_phone(self, phone: str) -> Optional[Dict]:
        """Busca un partner por teléfono o móvil. Prueba número completo y últimos 9 dígitos."""
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        # Intentar con el número completo y con los últimos 9 dígitos (sin prefijo país)
        search_variants = [clean_phone]
        if len(clean_phone) > 9:
            search_variants.append(clean_phone[-9:])  # Ej: 34606523222 → 606523222
        
        for variant in search_variants:
            domain = [
                '|',
                ('phone', 'ilike', variant),
                ('mobile', 'ilike', variant)
            ]
            partner_ids = self._execute_kw_with_retry('res.partner', 'search', [domain])
            if partner_ids:
                partners = self._execute_kw_with_retry(
                    'res.partner', 'read', [partner_ids],
                    {'fields': ['name', 'email', 'phone', 'mobile']}
                )
                log.info(f"Partner found: {partners[0]['name']} (variant: {variant[:4]}***)")
                return partners[0]
        
        log.info(f"No partner found for phone ***{clean_phone[-4:]}")
        return None

    def create_lead(self, name: str, phone: str, email: Optional[str] = None, description: Optional[str] = None) -> int:
        """Crea un lead en el CRM."""
        vals = {
            'name': name,
            'phone': phone,
            'email_from': email,
            'description': description,
            'type': 'opportunity'
        }
        lead_id: int = self._execute_kw_with_retry('crm.lead', 'create', [vals])
        log.info(f"Lead created: {lead_id}")
        return lead_id

    def schedule_meeting(self, partner_id: int, summary: str, start_date: str, duration: float = 1.0) -> int:
        """Agenda un evento en el calendario."""
        vals = {
            'name': summary,
            'start': start_date,
            'stop': start_date,
            'duration': duration,
            'partner_ids': [(4, partner_id)]
        }
        event_id: int = self._execute_kw_with_retry('calendar.event', 'create', [vals])
        log.info(f"Meeting scheduled: {event_id}")
        return event_id

    def check_availability(self, date_start: str, date_end: str) -> List[Dict]:
        """Lee el calendario entre dos fechas y devuelve eventos ocupados."""
        domain = [
            ('start', '<', date_end),
            ('stop', '>', date_start)
        ]
        event_ids = self._execute_kw_with_retry('calendar.event', 'search', [domain])
        if event_ids:
            return self._execute_kw_with_retry(
                'calendar.event', 'read', [event_ids],
                {'fields': ['name', 'start', 'stop']}
            )
        return []

    def create_full_booking(
        self, name: str, phone: str, email: str,
        description: str, start_date: str, duration: float = 1.0
    ) -> Dict[str, int]:
        """Crea Partner → Lead → Event de forma transaccional con rollback."""
        partner_id: Optional[int] = None
        lead_id: Optional[int] = None
        event_id: Optional[int] = None
        
        try:
            partner_id = self._execute_kw_with_retry('res.partner', 'create', [{
                'name': name, 'phone': phone, 'email': email
            }])

            lead_id = self._execute_kw_with_retry('crm.lead', 'create', [{
                'name': f"Oportunidad de {name}",
                'partner_id': partner_id,
                'description': description,
                'type': 'opportunity'
            }])

            event_id = self._execute_kw_with_retry('calendar.event', 'create', [{
                'name': f"Reunión Comercial: {name}",
                'start': start_date,
                'stop': start_date,
                'duration': duration,
                'partner_ids': [(4, partner_id)],
                'opportunity_id': lead_id
            }])

            log.info(f"Full booking: partner={partner_id}, lead={lead_id}, event={event_id}")
            return {'partner_id': partner_id, 'lead_id': lead_id, 'event_id': event_id}
            
        except Exception as e:
            log.error(f"Booking rollback triggered: {type(e).__name__}")
            if event_id:
                self._safe_delete('calendar.event', event_id)
            if lead_id:
                self._safe_delete('crm.lead', lead_id)
            if partner_id:
                self._safe_delete('res.partner', partner_id)
            raise
