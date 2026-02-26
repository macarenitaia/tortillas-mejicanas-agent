"""
Script para poblar Odoo (Tortillas Mejicanas) con datos de prueba.
Ejecutar con: python populate_dummy_data.py

Crea:
- 6 productos con precios y SKU
- 3 clientes de prueba
- Stock inicial para todos los productos
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_client import OdooClient

def populate():
    odoo = OdooClient()
    
    # ==========================================
    # 1. PRODUCTOS
    # ==========================================
    products = [
        {"name": "Tortillas de Maíz (Caja 10kg)",    "price": 25.50, "sku": "TM-MAIZ-10",   "stock": 200},
        {"name": "Tortillas de Trigo (Pack 12 uds)",  "price": 4.20,  "sku": "TM-TRIGO-12",  "stock": 500},
        {"name": "Totopos Naturales (Bolsa 500g)",    "price": 3.50,  "sku": "TM-TOT-500",   "stock": 300},
        {"name": "Salsa Verde Picante (Botella 1L)",  "price": 8.00,  "sku": "TM-SALSA-V1L", "stock": 150},
        {"name": "Masa de Maíz Nixtamalizada (1kg)",  "price": 2.10,  "sku": "TM-MASA-1KG",  "stock": 400},
        {"name": "Tortillas de Nopal (Pack 8 uds)",   "price": 5.90,  "sku": "TM-NOPAL-8",   "stock": 100},
    ]

    print("\n🌮 TORTILLAS MEJICANAS — Población de datos de prueba")
    print("=" * 55)
    
    print("\n📦 Creando productos...")
    created_products = []
    for p in products:
        try:
            template_id = odoo.create_product(p["name"], p["price"], p["sku"])
            variant_id = odoo.get_product_variant_id(template_id)
            created_products.append({
                "template_id": template_id, 
                "variant_id": variant_id,
                "name": p["name"],
                "stock": p["stock"]
            })
            print(f"  ✅ {p['name']} | {p['price']:.2f}€ | SKU: {p['sku']} | Template: {template_id}, Variant: {variant_id}")
        except Exception as e:
            print(f"  ❌ {p['name']}: {e}")

    # ==========================================
    # 2. STOCK INICIAL
    # ==========================================
    print("\n📊 Estableciendo stock inicial...")
    for cp in created_products:
        if cp["variant_id"]:
            try:
                result = odoo.update_product_stock(cp["variant_id"], cp["stock"])
                status = "✅" if result else "⚠️"
                print(f"  {status} {cp['name']}: {cp['stock']} unidades")
            except Exception as e:
                print(f"  ❌ {cp['name']}: {e}")
        else:
            print(f"  ⚠️ {cp['name']}: No se encontró variante de producto")

    # ==========================================
    # 3. CLIENTES DE PRUEBA
    # ==========================================
    clients = [
        {"name": "Restaurante El Mexicano",  "phone": "34611222333", "email": "contacto@elmexicano.es"},
        {"name": "Bar La Taquería",          "phone": "34622333444", "email": "info@lataqueria.es"},
        {"name": "Supermercado FreshMart",   "phone": "34633444555", "email": "compras@freshmart.es"},
    ]

    print("\n👥 Creando clientes de prueba...")
    for c in clients:
        try:
            partner_id = odoo.find_or_create_partner(c["name"], c["phone"], c["email"])
            print(f"  ✅ {c['name']} | Tel: {c['phone']} | ID: {partner_id}")
        except Exception as e:
            print(f"  ❌ {c['name']}: {e}")

    # ==========================================
    # 4. RESUMEN
    # ==========================================
    print("\n" + "=" * 55)
    print(f"✅ {len(created_products)} productos creados")
    print(f"✅ {len(clients)} clientes creados")
    print(f"✅ Stock inicial establecido")
    print("=" * 55)
    print("\n🚀 ¡Odoo listo para pruebas del agente!")
    print("   Prueba enviando por WhatsApp: 'quiero 4 cajas de tortillas de maíz'")

if __name__ == "__main__":
    populate()
