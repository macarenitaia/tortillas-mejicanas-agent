from crewai.tools import BaseTool
from odoo_client import OdooClient

odoo = OdooClient()

class OdooSearchTool(BaseTool):
    name: str = "Search Odoo Customer"
    description: str = "Searches for an existing customer in Odoo using their phone number. Returns customer details if found."

    def _run(self, phone: str) -> str:
        partner = odoo.search_partner_by_phone(phone)
        if partner:
            return f"Customer Found: {partner['name']} (ID: {partner['id']}). Email: {partner.get('email', 'N/A')}"
        return "Customer not found in Odoo."

class OdooLeadTool(BaseTool):
    name: str = "Create Odoo Lead"
    description: str = "Creates a new lead or sales opportunity in Odoo CRM. Requires name, phone, and a brief description of the query."

    def _run(self, name: str, phone: str, description: str, email: str = None) -> str:
        lead_id = odoo.create_lead(name, phone, email, description)
        if lead_id:
            return f"Success: Lead created in Odoo with ID {lead_id}."
        return "Error creating lead in Odoo."

class OdooCalendarTool(BaseTool):
    name: str = "Schedule Odoo Meeting"
    description: str = "Schedules a meeting in Odoo calendar for a customer. Requires partner_id, summary/title, and start_date (YYYY-MM-DD HH:MM:SS)."

    def _run(self, partner_id: int, summary: str, start_date: str) -> str:
        try:
            event_id = odoo.schedule_meeting(partner_id, summary, start_date)
            if event_id:
                return f"Success: Meeting scheduled. Event ID: {event_id}."
            return "Error scheduling meeting."
        except Exception as e:
            return f"Error: {str(e)}"
