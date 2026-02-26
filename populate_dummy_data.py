"""
Script para poblar Odoo con datos de prueba de Tortillas Mejicanas.
"""
from odoo_client import OdooClient
import os

def populate():
    odoo = OdooClient()
    
    products = [
        {"name": "Tortillas de Maíz (Caja 10kg)", "price": 25.50, "sku": "TM-MAIZ-10"},
        {"name": "Tortillas de Trigo (Pack 12 uds)", "price": 4.20, "sku": "TM-TRIGO-12"},
        {"name": "Totopos Naturales (Bolsa 500g)", "price": 3.50, "sku": "TM-TOT-NAT"},
        {"name": "Salsa Verde Picante (1L)", "price": 8.00, "sku": "TM-SALSA-V"},
        {"name": "Masa de Maíz Nixtamalizada (1kg)", "price": 2.10, "sku": "TM-MASA-1"},
    ]
    
    print("--- Iniciando población de datos ---")
    
    for p in products:
        try:
            # 1. Crear producto
            p_id = odoo.create_product(p["name"], p["price"], p["sku"])
            print(f"✅ Creado: {p['name']} (ID: {p_id})")
            
            # 2. Poner stock ficticio (buscamos el product.product ID)
            # Nota: create_product devuelve ID de product.template
            product_product = odoo.models.execute_kw(
                odoo.db, odoo.uid, odoo.password,
                'product.product', 'search', [[['product_tmpl_id', '=', p_id]]], {'limit': 1}
            )
            if product_product:
                odoo.update_product_stock(product_product[0], 100.0)
                print(f"   📦 Stock inicial: 100 unidades")
                
        except Exception as e:
            print(f"❌ Error con {p['name']}: {e}")

    print("--- Proceso finalizado ---")

if __name__ == "__main__":
    populate()
