import xmlrpc.client
import time
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
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

    def search_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """Busca un contacto por teléfono en res.partner Y crm.lead. Reconoce clientes y leads."""
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        if len(clean_phone) < 6:
            log.warning(f"Phone number too short for search: {phone}")
            return None
        
        # Variantes de búsqueda: número completo + últimos 9 dígitos (sin prefijo país)
        search_variants = [clean_phone]
        if len(clean_phone) > 9:
            search_variants.append(clean_phone[-9:])
        
        # 1) Buscar en res.partner (clientes/contactos)
        for variant in search_variants:
            domain = [('phone', 'ilike', variant)]
            partner_ids = self._execute_kw_with_retry('res.partner', 'search', [domain])
            if partner_ids:
                partners = self._execute_kw_with_retry(
                    'res.partner', 'read', [partner_ids],
                    {'fields': ['name', 'email', 'phone', 'street']}
                )
                log.info(f"Partner found: {partners[0]['name']}")
                return partners[0]
        
        # 2) Buscar en crm.lead (leads/oportunidades)
        for variant in search_variants:
            domain = [('phone', 'ilike', variant)]
            lead_ids = self._execute_kw_with_retry('crm.lead', 'search', [domain])
            if lead_ids:
                leads = self._execute_kw_with_retry(
                    'crm.lead', 'read', [lead_ids],
                    {'fields': ['contact_name', 'email_from', 'phone', 'partner_name', 'street']}
                )
                lead = leads[0]
                result = {
                    'name': lead.get('contact_name') or lead.get('partner_name') or 'Lead',
                    'email': lead.get('email_from', ''),
                    'phone': lead.get('phone', ''),
                    'street': lead.get('street', ''),
                }
                log.info(f"Lead found: {result['name']}")
                return result
        
        log.info(f"No contact found for phone ***{clean_phone[-4:]}")
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
        dt_start = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
        dt_stop = dt_start + timedelta(hours=duration)
        vals = {
            'name': summary,
            'start': start_date,
            'stop': dt_stop.strftime("%Y-%m-%d %H:%M:%S"),
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

            dt_start = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
            dt_stop = dt_start + timedelta(hours=duration)

            event_id = self._execute_kw_with_retry('calendar.event', 'create', [{
                'name': f"Reunión Comercial: {name}",
                'start': start_date,
                'stop': dt_stop.strftime("%Y-%m-%d %H:%M:%S"),
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

    # ==========================================
    # PRODUCTOS Y CATÁLOGO
    # ==========================================

    def search_products(self, query: str, limit: int = 10) -> List[Dict]:
        """Busca productos por nombre en product.product."""
        domain = [('name', 'ilike', query), ('sale_ok', '=', True)]
        product_ids = self._execute_kw_with_retry('product.product', 'search', [domain], {'limit': limit})
        if not product_ids:
            return []
        return self._execute_kw_with_retry(
            'product.product', 'read', [product_ids],
            {'fields': ['name', 'list_price', 'qty_available', 'uom_id', 'default_code']}
        )

    def get_product_stock(self, product_id: int) -> Dict:
        """Lee el stock disponible de un producto."""
        products = self._execute_kw_with_retry(
            'product.product', 'read', [[product_id]],
            {'fields': ['name', 'qty_available', 'virtual_available', 'uom_id']}
        )
        if products:
            p = products[0]
            log.info(f"Stock check: {p['name']} → {p['qty_available']} disponible")
            return p
        return {}

    # ==========================================
    # PARTNERS (buscar o crear)
    # ==========================================

    def find_or_create_partner(self, name: str, phone: str, email: Optional[str] = None) -> int:
        """Busca un partner por teléfono; si no existe, lo crea."""
        partner = self.search_contact_by_phone(phone)
        if partner and 'id' in partner:
            return partner['id']
        
        vals: Dict[str, Any] = {'name': name, 'phone': phone}
        if email:
            vals['email'] = email
        partner_id: int = self._execute_kw_with_retry('res.partner', 'create', [vals])
        log.info(f"Partner created: {partner_id} ({name})")
        return partner_id

    # ==========================================
    # PEDIDOS DE VENTA (sale.order)
    # ==========================================

    def create_sale_order(self, partner_id: int, order_lines: List[Dict]) -> Dict:
        """
        Crea un pedido de venta con líneas.
        order_lines: [{'product_id': int, 'quantity': float}, ...]
        Devuelve: {'order_id': int, 'order_name': str}
        """
        order_vals = {
            'partner_id': partner_id,
        }
        order_id: int = self._execute_kw_with_retry('sale.order', 'create', [order_vals])
        
        for line in order_lines:
            line_vals = {
                'order_id': order_id,
                'product_id': line['product_id'],
                'product_uom_qty': line.get('quantity', 1.0),
            }
            self._execute_kw_with_retry('sale.order.line', 'create', [line_vals])
        
        # Obtener el nombre del pedido
        order_data = self._execute_kw_with_retry(
            'sale.order', 'read', [[order_id]],
            {'fields': ['name', 'amount_total']}
        )
        order_name = order_data[0]['name'] if order_data else f"SO-{order_id}"
        amount = order_data[0].get('amount_total', 0) if order_data else 0
        
        log.info(f"Sale order created: {order_name} (ID: {order_id}), total: {amount}")
        return {'order_id': order_id, 'order_name': order_name, 'amount_total': amount}

    def confirm_sale_order(self, order_id: int) -> bool:
        """Confirma un pedido de venta (draft → sale)."""
        try:
            self._execute_kw_with_retry('sale.order', 'action_confirm', [[order_id]])
            log.info(f"Sale order {order_id} confirmed")
            
            # --- Enviar email de confirmación ---
            try:
                self._execute_kw_with_retry('sale.order', '_send_order_confirmation_mail', [[order_id]])
                log.info(f"Confirmation email sent for order {order_id}")
            except Exception as email_err:
                log.warning(f"Failed to send confirmation email for order {order_id}: {email_err}")

            return True
        except Exception as e:
            log.error(f"Confirm order {order_id} failed: {type(e).__name__}")
            raise

    def deliver_and_invoice_order(self, order_id: int) -> bool:
        """Valida la entrega (picking) y crea/publica la factura automáticamente."""
        try:
            # 1. Validar Pickings (Entregas)
            order_data = self._execute_kw_with_retry('sale.order', 'read', [[order_id]], {'fields': ['picking_ids']})
            picking_ids = order_data[0].get('picking_ids', [])
            
            for picking_id in picking_ids:
                picking = self._execute_kw_with_retry('stock.picking', 'read', [[picking_id]], {'fields': ['state']})[0]
                if picking['state'] not in ['done', 'cancel']:
                    # Odoo 16+ requiere setear cantidades
                    try:
                        self._execute_kw_with_retry('stock.picking', 'action_set_quantities_to_reservation', [[picking_id]])
                    except:
                        pass # Fallback si no existe
                    self._execute_kw_with_retry('stock.picking', 'button_validate', [[picking_id]])
                    log.info(f"Picking {picking_id} validated for order {order_id}")
            
            # 2. Crear Factura
            wizard_id = self._execute_kw_with_retry(
                'sale.advance.payment.inv', 'create',
                [{'advance_payment_method': 'delivered'}],
                {'context': {'active_ids': [order_id], 'active_model': 'sale.order'}}
            )
            self._execute_kw_with_retry(
                'sale.advance.payment.inv', 'create_invoices',
                [[wizard_id]],
                {'context': {'active_ids': [order_id], 'active_model': 'sale.order'}}
            )
            
            # 3. Publicar Factura
            order_data2 = self._execute_kw_with_retry('sale.order', 'read', [[order_id]], {'fields': ['invoice_ids']})
            invoice_ids = order_data2[0].get('invoice_ids', [])
            
            for inv_id in invoice_ids:
                self._execute_kw_with_retry('account.move', 'action_post', [[inv_id]])
                log.info(f"Invoice {inv_id} posted for order {order_id}")
                
            return True
        except Exception as e:
            log.error(f"Failed to auto-deliver/invoice order {order_id}: {type(e).__name__}: {e}")
            return False

    def generate_payment_link(self, order_id: int, amount: float) -> str:
        """Genera un enlace de pago para un pedido de venta mediante wizard."""
        try:
            wizard_vals = {
                'res_id': order_id,
                'res_model': 'sale.order',
                'amount': amount,
                'amount_max': amount,
            }
            wizard_id = self._execute_kw_with_retry('payment.link.wizard', 'create', [wizard_vals])
            wizard_data = self._execute_kw_with_retry(
                'payment.link.wizard', 'read', 
                [[wizard_id]], 
                {'fields': ['link']}
            )
            if wizard_data and wizard_data[0].get('link'):
                link = wizard_data[0]['link']
                log.info(f"Payment link generated: {link}")
                return link
            return ""
        except Exception as e:
            log.error(f"Payment link generation failed for order {order_id}: {type(e).__name__}")
            return ""

    # ==========================================
    # FACTURACIÓN (account.move)
    # ==========================================

    def create_invoice_from_order(self, order_id: int) -> Dict:
        """
        Genera una factura desde un pedido de venta confirmado.
        Usa el wizard sale.advance.payment.inv de Odoo.
        """
        try:
            # Crear wizard de facturación
            wizard_id = self._execute_kw_with_retry(
                'sale.advance.payment.inv', 'create',
                [{'advance_payment_method': 'delivered'}],
                {'context': {'active_ids': [order_id], 'active_model': 'sale.order'}}
            )
            # Ejecutar wizard
            self._execute_kw_with_retry(
                'sale.advance.payment.inv', 'create_invoices',
                [[wizard_id]],
                {'context': {'active_ids': [order_id], 'active_model': 'sale.order'}}
            )
            
            # Obtener la factura creada
            order_data = self._execute_kw_with_retry(
                'sale.order', 'read', [[order_id]],
                {'fields': ['invoice_ids']}
            )
            invoice_ids = order_data[0].get('invoice_ids', []) if order_data else []
            
            if invoice_ids:
                invoice = self._execute_kw_with_retry(
                    'account.move', 'read', [[invoice_ids[-1]]],
                    {'fields': ['name', 'amount_total', 'state']}
                )
                log.info(f"Invoice created: {invoice[0]['name']}")
                return invoice[0]
            
            return {'error': 'No se pudo obtener la factura creada'}
            
        except Exception as e:
            log.error(f"Invoice creation failed: {type(e).__name__}: {e}")
            raise

    # ==========================================
    # FABRICACIÓN (mrp.production)
    # ==========================================

    def create_manufacturing_order(self, product_id: int, quantity: float) -> Dict:
        """
        Crea una orden de fabricación para un producto.
        Requiere que el producto tenga una lista de materiales (BOM) en Odoo.
        """
        try:
            # Obtener info del producto
            product = self._execute_kw_with_retry(
                'product.product', 'read', [[product_id]],
                {'fields': ['name', 'uom_id']}
            )
            if not product:
                raise ValueError(f"Producto {product_id} no encontrado")
            
            product_name = product[0]['name']
            uom_id = product[0]['uom_id'][0] if product[0].get('uom_id') else False
            
            # Buscar BOM (Bill of Materials)
            bom_ids = self._execute_kw_with_retry(
                'mrp.bom', 'search',
                [[('product_tmpl_id.product_variant_ids', 'in', [product_id])]],
                {'limit': 1}
            )
            
            mo_vals: Dict[str, Any] = {
                'product_id': product_id,
                'product_qty': quantity,
                'product_uom_id': uom_id,
            }
            
            if bom_ids:
                mo_vals['bom_id'] = bom_ids[0]
            
            mo_id = self._execute_kw_with_retry('mrp.production', 'create', [mo_vals])
            
            log.info(f"Manufacturing order created: MO-{mo_id} for {quantity}x {product_name}")
            return {
                'mo_id': mo_id,
                'product': product_name,
                'quantity': quantity,
                'has_bom': bool(bom_ids)
            }
            
        except Exception as e:
            log.error(f"MRP creation failed: {type(e).__name__}: {e}")
            raise

    # ==========================================
    # UTILIDADES DE POBLACIÓN / PRUEBAS
    # ==========================================

    def create_product(self, name: str, price: float, sku: str = None) -> int:
        """Crea un nuevo producto en Odoo (product.template)."""
        vals = {
            'name': name,
            'list_price': price,
            'type': 'consu',  # Odoo SaaS 19: 'consu' = Goods (no stock tracking)
            'default_code': sku,
            'sale_ok': True,
            'purchase_ok': True,
        }
        product_id = self._execute_kw_with_retry('product.template', 'create', [vals])
        log.info(f"Product created: {name} (template ID: {product_id})")
        return product_id

    def get_product_variant_id(self, template_id: int) -> int:
        """Obtiene el product.product ID a partir del product.template ID."""
        variants = self._execute_kw_with_retry(
            'product.product', 'search',
            [[('product_tmpl_id', '=', template_id)]],
            {'limit': 1}
        )
        return variants[0] if variants else None

    def update_product_stock(self, product_id: int, quantity: float) -> bool:
        """Actualiza el stock de un producto via stock.quant (requiere product.product ID)."""
        try:
            # Encontrar ubicación interna de stock
            location_ids = self._execute_kw_with_retry(
                'stock.location', 'search',
                [[('usage', '=', 'internal')]],
                {'limit': 1}
            )
            if not location_ids:
                log.error("No internal stock location found")
                return False

            # Buscar quant existente o crear nuevo
            existing = self._execute_kw_with_retry(
                'stock.quant', 'search',
                [[('product_id', '=', product_id), ('location_id', '=', location_ids[0])]],
                {'limit': 1}
            )

            if existing:
                self._execute_kw_with_retry(
                    'stock.quant', 'write',
                    [existing, {'inventory_quantity': quantity}]
                )
                quant_id = existing[0]
            else:
                quant_id = self._execute_kw_with_retry(
                    'stock.quant', 'create',
                    [{'product_id': product_id, 'location_id': location_ids[0], 'inventory_quantity': quantity}]
                )

            # Aplicar el ajuste de inventario
            self._execute_kw_with_retry(
                'stock.quant', 'action_apply_inventory',
                [[quant_id if isinstance(quant_id, int) else quant_id]]
            )
            log.info(f"Stock updated for product {product_id}: {quantity} units")
            return True
        except Exception as e:
            log.error(f"Stock update failed: {type(e).__name__}: {e}")
            return False


