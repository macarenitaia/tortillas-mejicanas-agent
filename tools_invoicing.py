"""
Herramientas CrewAI para facturación y fabricación (MRP) en Odoo.
Genera facturas desde pedidos confirmados y crea órdenes de fabricación.
"""
from crewai.tools import BaseTool
from odoo_client import OdooClient
from logger import get_logger

log = get_logger("tools_invoicing")

odoo = OdooClient()


class CreateInvoiceTool(BaseTool):
    """Genera una factura desde un pedido de venta confirmado."""
    name: str = "Create Invoice"
    description: str = (
        "Creates an invoice from a confirmed sale order. "
        "Requires: order_id (the sale order ID returned by Create Sale Order tool). "
        "The order must be in 'confirmed' state. Returns invoice reference and total."
    )

    def _run(self, order_id: int) -> str:
        try:
            invoice = odoo.create_invoice_from_order(int(order_id))
            
            if 'error' in invoice:
                return f"⚠️ {invoice['error']}"
            
            return (
                f"✅ Factura generada:\n"
                f"- Referencia: {invoice.get('name', 'N/A')}\n"
                f"- Total: {invoice.get('amount_total', 0):.2f}€\n"
                f"- Estado: {invoice.get('state', 'borrador')}"
            )
        except Exception as e:
            log.error(f"CreateInvoiceTool error: {type(e).__name__}: {e}")
            return f"Error generando factura: {str(e)}"


class CreateManufacturingOrderTool(BaseTool):
    """Crea una orden de fabricación cuando no hay stock suficiente."""
    name: str = "Create Manufacturing Order"
    description: str = (
        "Creates a manufacturing/production order for a product when stock is insufficient. "
        "Requires: product_id (product ID), quantity (number to manufacture). "
        "The product should have a Bill of Materials (BOM) configured in Odoo. "
        "Returns the manufacturing order reference."
    )

    def _run(self, product_id: int, quantity: float) -> str:
        try:
            mo = odoo.create_manufacturing_order(int(product_id), float(quantity))
            
            bom_note = ""
            if not mo.get('has_bom'):
                bom_note = "\n⚠️ NOTA: No se encontró lista de materiales (BOM). Se creó la orden pero puede requerir configuración manual."
            
            return (
                f"🏭 Orden de fabricación creada:\n"
                f"- Referencia: MO-{mo['mo_id']}\n"
                f"- Producto: {mo['product']}\n"
                f"- Cantidad: {mo['quantity']}"
                f"{bom_note}"
            )
        except Exception as e:
            log.error(f"CreateManufacturingOrderTool error: {type(e).__name__}: {e}")
            return f"Error creando orden de fabricación: {str(e)}"
