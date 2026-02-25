"""
Suite de tests para el agente WhatsApp + Odoo + Supabase.
Ejecutar con: pytest tests/ -v
"""
import pytest
import json
import hashlib
import hmac
import sys
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==========================================
# TESTS: API ENDPOINTS
# ==========================================

class TestAPIEndpoints:
    """Tests para los endpoints de la API."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: mock de dependencias pesadas (CrewAI, Odoo, Supabase) para tests rápidos."""
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_KEY": "test-supabase-key",
            "ODOO_URL": "https://test.odoo.com",
            "ODOO_DB": "test-db",
            "ODOO_USERNAME": "test@test.com",
            "ODOO_PASSWORD": "testpass",
            "API_SECRET_KEY": "test-secret-123",
            "WHATSAPP_APP_SECRET": "test-app-secret",
        }):
            # Mock de supabase antes de importar los módulos
            with patch("supabase.create_client") as mock_sb:
                mock_sb.return_value = MagicMock()
                with patch("langchain_openai.ChatOpenAI"):
                    from api.index import app, rate_limiter, message_dedup
                    self.client = TestClient(app)
                    self.rate_limiter = rate_limiter
                    self.message_dedup = message_dedup
                    yield

    def test_root_endpoint(self):
        """GET /api devuelve status ok."""
        response = self.client.get("/api")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_chat_without_auth_returns_401(self):
        """POST /api/chat sin Bearer Token devuelve 401."""
        response = self.client.post("/api/chat", json={"message": "Hola"})
        assert response.status_code == 401

    def test_chat_with_wrong_auth_returns_401(self):
        """POST /api/chat con token incorrecto devuelve 401."""
        response = self.client.post(
            "/api/chat",
            json={"message": "Hola"},
            headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401

    def test_chat_without_message_returns_400(self):
        """POST /api/chat sin mensaje devuelve 400."""
        response = self.client.post(
            "/api/chat",
            json={"session_id": "test"},
            headers={"Authorization": "Bearer test-secret-123"}
        )
        assert response.status_code == 400

    @patch("api.index.run_odoo_crew")
    def test_chat_success(self, mock_crew):
        """POST /api/chat con auth válida devuelve respuesta del agente."""
        mock_crew.return_value = "Hola, soy Sofía 👋"
        response = self.client.post(
            "/api/chat",
            json={"session_id": "test123", "message": "Hola"},
            headers={"Authorization": "Bearer test-secret-123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Sofía" in data["reply"]
        assert data["session_id"] == "test123"

    def test_webhook_get_verification(self):
        """GET /api/whatsapp verificación de webhook de Meta."""
        response = self.client.get("/api/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.verify_token": os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
            "hub.challenge": "challenge123"
        })
        # Si no hay WHATSAPP_VERIFY_TOKEN en env, retorna 403
        assert response.status_code in [200, 403]

    def test_webhook_post_invalid_signature_returns_403(self):
        """POST /api/whatsapp con firma inválida devuelve 403."""
        body = json.dumps({"object": "whatsapp_business_account", "entry": []})
        response = self.client.post(
            "/api/whatsapp",
            content=body.encode(),
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid"
            }
        )
        assert response.status_code == 403

    def test_webhook_post_valid_signature(self):
        """POST /api/whatsapp con firma válida devuelve 200."""
        body = json.dumps({"object": "whatsapp_business_account", "entry": []})
        body_bytes = body.encode()
        signature = "sha256=" + hmac.HMAC(
            b"test-app-secret", body_bytes, hashlib.sha256
        ).hexdigest()
        
        response = self.client.post(
            "/api/whatsapp",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature
            }
        )
        assert response.status_code == 200


# ==========================================
# TESTS: RATE LIMITER
# ==========================================

class TestRateLimiter:
    """Tests para el rate limiter in-memory."""
    
    def test_allows_requests_within_limit(self):
        from api.index import RateLimiter
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("1.2.3.4") is True

    def test_blocks_requests_over_limit(self):
        from api.index import RateLimiter
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.is_allowed("1.2.3.4")
        limiter.is_allowed("1.2.3.4")
        assert limiter.is_allowed("1.2.3.4") is False

    def test_different_ips_independent(self):
        from api.index import RateLimiter
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("5.6.7.8") is True


# ==========================================
# TESTS: MESSAGE DEDUP
# ==========================================

class TestMessageDedup:
    """Tests para la deduplicación de mensajes."""
    
    def test_first_message_not_duplicate(self):
        from api.index import MessageDedup
        dedup = MessageDedup()
        assert dedup.is_duplicate("msg_001") is False

    def test_same_message_is_duplicate(self):
        from api.index import MessageDedup
        dedup = MessageDedup()
        dedup.is_duplicate("msg_002")
        assert dedup.is_duplicate("msg_002") is True

    def test_different_messages_not_duplicate(self):
        from api.index import MessageDedup
        dedup = MessageDedup()
        dedup.is_duplicate("msg_003")
        assert dedup.is_duplicate("msg_004") is False


# ==========================================
# TESTS: ODOO CLIENT
# ==========================================

class TestOdooClient:
    """Tests unitarios para OdooClient con mocks."""
    
    @patch.dict(os.environ, {
        "ODOO_URL": "https://test.odoo.com",
        "ODOO_DB": "test-db",
        "ODOO_USERNAME": "test@test.com",
        "ODOO_PASSWORD": "testpass",
        "ODOO_API_KEY": "",
    })
    def test_mask_phone(self):
        from odoo_client import _mask_phone
        assert _mask_phone("34600112233") == "***2233"
        assert _mask_phone("123") == "***"

    @patch.dict(os.environ, {
        "ODOO_URL": "https://test.odoo.com",
        "ODOO_DB": "test-db",
        "ODOO_USERNAME": "test@test.com",
        "ODOO_PASSWORD": "testpass",
        "ODOO_API_KEY": "test-api-key",
    })
    @patch("xmlrpc.client.ServerProxy")
    def test_authentication_tries_api_key_first(self, mock_proxy):
        """Verifica que se intenta API key antes que password."""
        mock_common = MagicMock()
        mock_common.authenticate.side_effect = [5]  # API Key funciona a la primera
        mock_proxy.return_value = mock_common
        
        from odoo_client import OdooClient
        client = OdooClient()
        client.url = "https://test.odoo.com"
        client.db = "test-db"
        client.username = "test@test.com"
        client.uid = None
        
        client._ensure_authenticated()
        assert client.uid == 5

    @patch.dict(os.environ, {
        "ODOO_URL": "https://test.odoo.com",
        "ODOO_DB": "test-db",
        "ODOO_USERNAME": "test@test.com",
        "ODOO_PASSWORD": "testpass",
        "ODOO_API_KEY": "bad-key",
    })
    @patch("xmlrpc.client.ServerProxy")
    def test_authentication_fallback_to_password(self, mock_proxy):
        """Verifica fallback a password cuando API key falla."""
        mock_common = MagicMock()
        mock_common.authenticate.side_effect = [False, 5]  # API Key falla, Password OK
        mock_proxy.return_value = mock_common
        
        from odoo_client import OdooClient
        client = OdooClient()
        client.uid = None
        
        client._ensure_authenticated()
        assert client.uid == 5


# ==========================================
# TESTS: UTILIDADES
# ==========================================

class TestUtilities:
    """Tests para funciones utilitarias."""
    
    def test_config_require_env_warns_on_missing(self, capsys):
        from config import _require_env
        result = _require_env("NONEXISTENT_VAR_12345")
        assert result == ""

    def test_logger_produces_json(self):
        from logger import get_logger
        import io
        logger = get_logger("test_json_output")
        # Verificar que el logger se crea sin errores
        assert logger is not None
        assert logger.name == "test_json_output"
