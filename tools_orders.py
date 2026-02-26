"""
Herramientas CrewAI para gestión de pedidos en Odoo.
Buscar productos, verificar stock, crear pedidos de venta y confirmarlos.
"""
from crewai.tools import BaseTool
from odoo_client import OdooClient
from logger import get_logger

log = get_logger("tools_orders")

odoo = OdooClient()


class ProductSearchTool(BaseTool):
    """Busca productos en el catálogo de Odoo por nombre."""
    name: str = "Search Products"
    description: str = (
        "Searches for products in the catalog by name. Returns product name, price, "
        "available stock, and unit of measure. Use this when a client asks about a product "
        "or wants to place an order. Input: query (product name or partial name)."
    )

    def _run(self, query: str) -> str:
        try:
            products = odoo.search_products(query)
            if not products:
                return f"No se encontraron productos con '{query}' en el catálogo."
            
            result = f"Productos encontrados ({len(products)}):\n"
            for p in products:
                uom = p.get('uom_id', [0, 'ud'])[1] if p.get('uom_id') else 'ud'
                result += (
                    f"- {p['name']} (ID: {p['id']}) | "
                    f"Precio: {p.get('list_price', 0):.2f}€ | "
                    f"Stock: {p.get('qty_available', 0):.0f} {uom} | "
                    f"Ref: {p.get('default_code', 'N/A')}\n"
                )
            return result
        except Exception as e:
            log.error(f"ProductSearchTool error: {type(e).__name__}")
            return f"Error buscando productos: {str(e)}"


class InventoryCheckTool(BaseTool):
    """Verifica el stock disponible de un producto específico."""
    name: str = "Check Inventory"
    description: str = (
        "Checks the available stock for a specific product by its ID. "
        "Returns current stock and forecasted stock. Use this before creating "
        "an order to verify product availability. Input: product_id (integer)."
    )

    def _run(self, product_id: int) -> str:
        try:
            stock = odoo.get_product_stock(int(product_id))
            if not stock:
                return f"No se encontró el producto con ID {product_id}."
            
            uom = stock.get('uom_id', [0, 'ud'])[1] if stock.get('uom_id') else 'ud'
            return (
                f"Stock de '{stock['name']}':\n"
                f"- Disponible ahora: {stock.get('qty_available', 0):.0f} {uom}\n"
                f"- Previsto (incluyendo pedidos entrantes): {stock.get('virtual_available', 0):.0f} {uom}"
            )
        except Exception as e:
            log.error(f"InventoryCheckTool error: {type(e).__name__}")
            return f"Error verificando inventario: {str(e)}"


class CreateSaleOrderTool(BaseTool):
    """Crea un pedido de venta completo en Odoo."""
    name: str = "Create Sale Order"
    description: str = (
        "Creates a complete sale order with product lines, auto-validates delivery and creates invoice. "
        "Requires: name (client name), phone (client phone), address (delivery address), email (client email, optional), "
        "product_id (product ID from search), quantity (number of units). "
        "This tool will find or create the customer, update their address, create the order, confirm it, and invoice it. "
        "Returns the order reference number, total amount, and payment link."
    )

    def _run(self, name: str, phone: str, address: str, product_id: int, quantity: float, email: str = "") -> str:
        try:
            # 1. Buscar o crear partner
            partner_id = odoo.find_or_create_partner(name, phone, email if email else None)
            
            # Actualizar dirección
            odoo._execute_kw_with_retry('res.partner', 'write', [[partner_id], {'street': address}])
            
            # 2. Crear pedido con líneas
            order_lines = [{'product_id': int(product_id), 'quantity': float(quantity)}]
            order = odoo.create_sale_order(partner_id, order_lines)
            
            # 3. Confirmar el pedido (esto envía el email proforma/pedido inicial)
            odoo.confirm_sale_order(order['order_id'])
            
            # 4. Auto-entregar y facturar
            invoice_success = odoo.deliver_and_invoice_order(order['order_id'])
            
            # 5. Generar enlace de pago
            payment_link = odoo.generate_payment_link(order['order_id'], order['amount_total'])
            link_text = f"\n- Enlace de Pago Seguro: {payment_link}" if payment_link else ""
            
            invoice_status = "El pedido ha sido procesado, entregado y facturado automáticamente." if invoice_success else "El pedido está confirmado."
            
            return (
                f"✅ Pedido creado exitosamente:\n"
                f"- Referencia: {order['order_name']}\n"
                f"- Producto ID: {product_id} x {quantity} ud(s)\n"
                f"- Total a pagar: {order['amount_total']:.2f}€\n"
                f"- Dirección de Entrega: {address}\n"
                f"{invoice_status} Se ha enviado un correo con los detalles.{link_text}"
            )
        except Exception as e:
            log.error(f"CreateSaleOrderTool error: {type(e).__name__}: {e}")
            return f"Error creando pedido: {str(e)}"
