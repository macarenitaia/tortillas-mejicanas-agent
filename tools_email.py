"""
Herramienta de envío de emails para el agente Sofía via Resend API.
Se usa para enviar confirmaciones de reunión al cliente después de agendar.
"""
import httpx
from crewai.tools import BaseTool
from config import RESEND_API_KEY, EMAIL_FROM
from logger import get_logger

log = get_logger("tools_email")


class SendEmailTool(BaseTool):
    """Envía un email de confirmación de reunión al cliente."""
    name: str = "Send Email"
    description: str = (
        "Sends a confirmation email to the client after booking a meeting. "
        "Requires: to_email (recipient email), subject (email subject), "
        "body (email body in plain text). "
        "Use this AFTER successfully booking a meeting with OdooFullBookingTool."
    )

    def _run(self, to_email: str, subject: str, body: str) -> str:
        if not RESEND_API_KEY:
            log.warning("RESEND_API_KEY not configured, skipping email")
            return "Email service not configured. Meeting was booked but confirmation email was not sent."
        
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": _build_html_email(subject, body)
                },
                timeout=15.0
            )
            
            if response.status_code in [200, 201]:
                log.info(f"Email sent to {to_email[:3]}***")
                return f"Email de confirmación enviado correctamente a {to_email}."
            else:
                log.error(f"Resend failed: HTTP {response.status_code} - {response.text[:200]}")
                return f"No se pudo enviar el email (error {response.status_code}). La reunión fue agendada correctamente."
                
        except Exception as e:
            log.error(f"Email send error: {type(e).__name__}")
            return "Error al enviar el email, pero la reunión fue agendada correctamente en el calendario."


def _build_html_email(subject: str, body: str) -> str:
    """Construye un email HTML profesional con el branding de Real to Digital."""
    # Convertir saltos de línea del body a <br>
    body_html = body.replace("\n", "<br>")
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background-color:#f4f4f7;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:32px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
                        <!-- Header -->
                        <tr>
                            <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:32px 40px;text-align:center;">
                                <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;">Real to Digital</h1>
                                <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">Transformamos tu negocio</p>
                            </td>
                        </tr>
                        <!-- Body -->
                        <tr>
                            <td style="padding:40px;">
                                <h2 style="color:#1a1a2e;margin:0 0 20px;font-size:20px;">{subject}</h2>
                                <div style="color:#4a5568;font-size:15px;line-height:1.7;">
                                    {body_html}
                                </div>
                            </td>
                        </tr>
                        <!-- Footer -->
                        <tr>
                            <td style="background:#f8f9fa;padding:24px 40px;text-align:center;border-top:1px solid #e2e8f0;">
                                <p style="color:#a0aec0;font-size:12px;margin:0;">
                                    © 2026 Real to Digital · Este email fue enviado automáticamente por nuestra asistente Sofía.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
