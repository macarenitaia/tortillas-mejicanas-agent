"""
Herramienta de envío de emails para el agente Sofía via Odoo mail.mail.
Usa el servidor de correo ya configurado en Odoo, y el email queda registrado en el CRM.
"""
from crewai.tools import BaseTool
from logger import get_logger

log = get_logger("tools_email")


class SendEmailTool(BaseTool):
    """Envía un email de confirmación de reunión al cliente a través de Odoo."""
    name: str = "Send Email"
    description: str = (
        "Sends a confirmation email to the client after booking a meeting. "
        "Requires: to_email (recipient email), subject (email subject), "
        "body (email body text with meeting details like date, time, etc). "
        "Use this AFTER successfully booking a meeting with OdooFullBookingTool."
    )

    def _run(self, to_email: str, subject: str, body: str) -> str:
        try:
            # Lazy import para evitar crash al importar el módulo
            from tools_odoo import odoo
            
            body_html = _build_html_email(subject, body)
            
            # Crear el mail.mail en Odoo
            mail_vals = {
                'subject': subject,
                'email_from': odoo.username,  # Usa el email del usuario de Odoo
                'email_to': to_email,
                'body_html': body_html,
                'auto_delete': True,
            }
            
            mail_id = odoo._execute_kw_with_retry('mail.mail', 'create', [mail_vals])
            
            # Enviar el email inmediatamente
            odoo._execute_kw_with_retry('mail.mail', 'send', [[mail_id]])
            
            log.info(f"Email sent via Odoo to {to_email[:3]}***")
            return f"Email de confirmación enviado correctamente a {to_email} a través de Odoo."
            
        except Exception as e:
            log.error(f"Odoo email error: {type(e).__name__}: {e}")
            return f"No se pudo enviar el email, pero la reunión fue agendada correctamente en el calendario."


def _build_html_email(subject: str, body: str) -> str:
    """Construye un email HTML profesional con el branding de Real to Digital."""
    body_html = body.replace("\n", "<br>")
    
    return f"""
    <div style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background-color:#f4f4f7;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:32px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
                        <tr>
                            <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:32px 40px;text-align:center;">
                                <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;">Real to Digital</h1>
                                <p style="color:#a0aec0;margin:8px 0 0;font-size:14px;">Transformamos tu negocio</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:40px;">
                                <h2 style="color:#1a1a2e;margin:0 0 20px;font-size:20px;">{subject}</h2>
                                <div style="color:#4a5568;font-size:15px;line-height:1.7;">
                                    {body_html}
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td style="background:#f8f9fa;padding:24px 40px;text-align:center;border-top:1px solid #e2e8f0;">
                                <p style="color:#a0aec0;font-size:12px;margin:0;">
                                    &copy; 2026 Real to Digital &middot; Email enviado por nuestra asistente Sof&iacute;a.
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </div>
    """
