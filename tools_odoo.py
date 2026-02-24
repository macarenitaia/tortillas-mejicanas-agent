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

class OdooCheckAvailabilityTool(BaseTool):
    name: str = "Check Calendar Availability"
    description: str = "Reads Odoo calendar between date_start and date_end (YYYY-MM-DD HH:MM:SS) to find booked meetings. If it returns an empty list, the slot is free. Always check this before booking."

    def _run(self, date_start: str, date_end: str) -> str:
        try:
            events = odoo.check_availability(date_start, date_end)
            if events:
                return f"Busy slots found: {events}"
            return "The calendar is free in this time range."
        except Exception as e:
            return f"Error checking availability: {str(e)}"

class OdooFullBookingTool(BaseTool):
    name: str = "Create Full Booking (Lead & Meeting)"
    description: str = "Creates a Partner, a Lead, and schedules the Meeting all at once. Requires name, phone, email, description, and start_date (YYYY-MM-DD HH:MM:SS)."

    def _run(self, name: str, phone: str, email: str, description: str, start_date: str) -> str:
        try:
            res = odoo.create_full_booking(name, phone, email, description, start_date)
            return f"Success: Partner ({res['partner_id']}), Lead ({res['lead_id']}), and Meeting ({res['event_id']}) created strictly in Odoo."
        except Exception as e:
            return f"Error creating booking in Odoo: {str(e)}"
