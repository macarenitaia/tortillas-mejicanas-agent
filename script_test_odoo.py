import os
from dotenv import load_dotenv

# Cargar .env antes de importar odoo_client
load_dotenv()

from odoo_client import OdooClient
import json

def test():
    odoo = OdooClient()
    print("Autenticado.")
    
    # Buscar el último pedido confirmado
    orders = odoo._execute_kw_with_retry(
        'sale.order', 'search_read', 
        [[('state', '=', 'sale')]], 
        {'limit': 1, 'fields': ['name', 'access_token', 'access_url', 'amount_total']}
    )
    
    if not orders:
        print("No hay pedidos de venta confirmados.")
        return
        
    order = orders[0]
    print(f"Pedido: {order['name']}")
    print(f"URL de acceso interno: {order.get('access_url')}")
    print(f"Token de acceso: {order.get('access_token')}")
    print(f"Total: {order.get('amount_total')}")
    
    # Intentar generar payment link usando payment.link.wizard
    try:
        wizard_vals = {
            'res_id': order['id'],
            'res_model': 'sale.order',
            'amount': order.get('amount_total', 0),
            'amount_max': order.get('amount_total', 0),
        }
        wizard_id = odoo._execute_kw_with_retry('payment.link.wizard', 'create', [wizard_vals])
        wizard_data = odoo._execute_kw_with_retry(
            'payment.link.wizard', 'read', 
            [[wizard_id]], 
            {'fields': ['link']}
        )
        if wizard_data:
            print(f"Enlace de pago generado: {wizard_data[0].get('link')}")
    except Exception as e:
        print(f"Error generando payment link: {e}")

    # Intentar enviar el email de confirmación
    try:
        res = odoo._execute_kw_with_retry('sale.order', '_send_order_confirmation_mail', [[order['id']]])
        print(f"Envío de email automático: {res}")
    except Exception as e:
        print(f"Error enviando email: {e}")

if __name__ == '__main__':
    test()
