"""Unit tests for the document upload system.

Root cause fixed (pre-existing, not caused by provisioning changes):
The upload endpoint depends on:
  1. get_current_user → verify_token (JWKS) + db.execute (Postgres users table)
  2. get_db → tenant_scoped_session (Postgres)
  3. store_document (app.db.storage) → writes to S3 / local disk
  4. process_document.delay (app.tasks.ingestion) → Celery task broker

All four are mocked via:
  - app.dependency_overrides for get_db (makes get_current_user's inner
    db.execute work with a no-op mock session)
  - patch() for store_document and process_document.delay

The JWKS layer is already mocked via the autouse fixture mock_jwks_upload.
"""

import io
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

import app.tasks.ingestion
from app.api.deps import get_db
from app.auth.jwt_auth import User
from app.models.domain import DataSource
from main import app


# --- Token/Auth mock shared fixture -------------------------------------------
_UPLOAD_TOKEN_PAYLOADS = {
    "admin_token": {
        "sub": "auth0|admin",
        "https://aegis-api/org_id": "00000000-0000-0000-0000-000000000001",
        "https://aegis-api/team_ids": ["10000000-0000-0000-0000-000000000001"],
        "https://aegis-api/roles": {"10000000-0000-0000-0000-000000000001": "org_admin"},
    },
    "employee_token": {
        "sub": "auth0|employee",
        "https://aegis-api/org_id": "00000000-0000-0000-0000-000000000001",
        "https://aegis-api/team_ids": ["10000000-0000-0000-0000-000000000002"],
        "https://aegis-api/roles": {"10000000-0000-0000-0000-000000000002": "employee"},
    },
}


@pytest.fixture(autouse=True)
def mock_jwks_upload():
    """Patch JWKS verification so upload tests don't hit the network."""
    def decode_side_effect(token, key, algorithms, audience, issuer):
        if token in _UPLOAD_TOKEN_PAYLOADS:
            return _UPLOAD_TOKEN_PAYLOADS[token]
        import jwt as jwt_lib
        raise jwt_lib.InvalidSignatureError("Signature verification failed")

    mock_key = MagicMock()
    mock_key.key = "fake-public-key"
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    with (
        patch("app.auth.auth0_verify.jwt.PyJWKClient", return_value=mock_client),
        patch("app.auth.auth0_verify.jwt.decode", side_effect=decode_side_effect),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_db_upload():
    """Override get_db so upload tests don't hit Postgres.

    Mocks queries for user lookup and team memberships to allow correct
    RBAC resolution during document upload validation.
    """
    mock_db = AsyncMock()

    user_admin_id = uuid.UUID("30000000-0000-0000-0000-000000000001")
    user_employee_id = uuid.UUID("30000000-0000-0000-0000-000000000002")

    async def _execute(stmt, params=None):
        sql = str(stmt).strip().upper()
        result = MagicMock()

        if "FROM USERS" in sql:
            sub = params.get("sub") if params else None
            if sub == "auth0|admin":
                result.fetchone.return_value = (user_admin_id,)
            elif sub == "auth0|employee":
                result.fetchone.return_value = (user_employee_id,)
            else:
                result.fetchone.return_value = None
        elif "FROM TEAM_MEMBERSHIPS" in sql:
            user_id = params.get("user_id") if params else None
            if user_id == user_admin_id:
                result.fetchall.return_value = [("org_admin", None)]
            elif user_id == user_employee_id:
                result.fetchall.return_value = [("employee", None)]
            else:
                result.fetchall.return_value = []
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []

        return result

    mock_db.execute = AsyncMock(side_effect=_execute)
    app.dependency_overrides[get_db] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def mock_storage_and_celery():
    """Mock S3 storage and Celery task broker used by the upload endpoint."""
    fake_job = MagicMock()
    fake_job.id = str(uuid.uuid4())

    with (
        patch("app.api.routes.store_document", return_value="s3://fake/path"),
        patch("app.tasks.ingestion.process_document") as mock_task,
    ):
        mock_task.delay.return_value = fake_job
        yield


@pytest.fixture
def auth_headers():
    return {
        "admin": {"Authorization": "Bearer admin_token"},
        "employee": {"Authorization": "Bearer employee_token"},
    }


class TestUploadRBAC:
    def test_admin_upload_allowed(self, auth_headers):
        # Admin can access SALARY_RECORDS
        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.txt", b"salary content here", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()
        assert data["filename"] == "salaries.txt"
        assert data["data_source"] == DataSource.SALARY_RECORDS.value

    def test_employee_upload_denied_sensitive_source(self, auth_headers):
        # Employee cannot access SALARY_RECORDS
        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["employee"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.txt", b"salary content here", "text/plain")},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
        assert "Access Denied" in response.json()["detail"]

    def test_employee_upload_allowed_permitted_source(self, auth_headers):
        # Employee can access PUBLIC_POLICIES
        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["employee"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("handbook.txt", b"Employee handbook content", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text


class TestFileParsers:
    def test_txt_upload(self, auth_headers):
        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("policy.txt", b"Policy details text.\nMore policy info.", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    def test_csv_upload(self, auth_headers):
        csv_data = b"server_id,cpu_percent,status\nprod-1,90,critical\nprod-2,50,ok\n"
        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.OPERATIONAL_DATASETS.value},
            files={"file": ("metrics.csv", csv_data, "text/csv")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    def test_json_upload(self, auth_headers):
        json_data = json.dumps([
            {"timestamp": "2026-06-15", "event_type": "login_failed", "username": "admin"},
            {"timestamp": "2026-06-15", "event_type": "login_success", "username": "user1"}
        ]).encode("utf-8")

        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.AUDIT_LOGS.value},
            files={"file": ("audit.json", json_data, "application/json")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    @patch("pypdf.PdfReader")
    def test_pdf_upload(self, mock_pdf_reader, auth_headers):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is a compliance document content"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader

        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.COMPLIANCE_RECORDS.value},
            files={"file": ("report.pdf", b"fake pdf bytes", "application/pdf")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    @patch("docx.Document")
    def test_docx_upload(self, mock_docx_document, auth_headers):
        mock_paragraph = MagicMock()
        mock_paragraph.text = "This is paragraph content from word file."
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_paragraph]
        mock_docx_document.return_value = mock_doc

        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("guide.docx", b"fake docx bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    @patch("openpyxl.load_workbook")
    def test_excel_upload(self, mock_load_workbook, auth_headers):
        mock_sheet = MagicMock()
        mock_sheet.iter_rows.return_value = [
            ("Employee", "Salary"),
            ("Alice", 120000),
            ("Bob", 95000),
        ]
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Salaries"]
        mock_wb.__getitem__.return_value = mock_sheet
        mock_load_workbook.return_value = mock_wb

        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.xlsx", b"fake excel bytes", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text

    @patch("PIL.Image.open")
    def test_image_upload(self, mock_image_open, auth_headers):
        mock_image = MagicMock()
        mock_image.format = "JPEG"
        mock_image.width = 1024
        mock_image.height = 768
        mock_image.mode = "RGB"
        mock_image._getexif.return_value = {271: b"Canon", 272: b"EOS 5D"}
        mock_image_open.return_value = mock_image

        client = TestClient(app)
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.INFRASTRUCTURE_REPORTS.value},
            files={"file": ("datacenter.jpg", b"fake image bytes", "image/jpeg")},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
