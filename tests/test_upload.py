"""Unit tests for the document upload system."""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.api.deps import get_auth_service, get_vector_store
from app.auth.jwt_auth import User
from app.models.domain import DataSource, UserRole
from main import app

client = TestClient(app)


@pytest.fixture
def auth_headers():
    auth = get_auth_service()
    
    # Admin User Headers
    admin = User("admin_user", UserRole.ADMIN, "IT")
    admin_token, _ = auth.create_token(admin)
    
    # Employee User Headers
    employee = User("employee_user", UserRole.EMPLOYEE, "HR")
    employee_token, _ = auth.create_token(employee)
    
    return {
        "admin": {"Authorization": f"Bearer {admin_token}"},
        "employee": {"Authorization": f"Bearer {employee_token}"},
    }


class TestUploadRBAC:
    def test_admin_upload_allowed(self, auth_headers):
        # Admin can access SALARY_RECORDS
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.txt", b"salary content here", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["filename"] == "salaries.txt"
        assert data["data_source"] == DataSource.SALARY_RECORDS.value

    def test_employee_upload_denied_sensitive_source(self, auth_headers):
        # Employee cannot access SALARY_RECORDS
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["employee"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.txt", b"salary content here", "text/plain")},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Access Denied" in response.json()["detail"]

    def test_employee_upload_allowed_permitted_source(self, auth_headers):
        # Employee can access PUBLIC_POLICIES
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["employee"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("handbook.txt", b"Employee handbook content", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK


class TestFileParsers:
    def test_txt_upload(self, auth_headers):
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("policy.txt", b"Policy details text.\nMore policy info.", "text/plain")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["chunks_ingested"] > 0

    def test_csv_upload(self, auth_headers):
        csv_data = b"server_id,cpu_percent,status\nprod-1,90,critical\nprod-2,50,ok\n"
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.OPERATIONAL_DATASETS.value},
            files={"file": ("metrics.csv", csv_data, "text/csv")},
        )
        assert response.status_code == status.HTTP_200_OK
        # 2 data rows = 2 chunks
        assert response.json()["chunks_ingested"] == 2

    def test_json_upload(self, auth_headers):
        json_data = json.dumps([
            {"timestamp": "2026-06-15", "event_type": "login_failed", "username": "admin"},
            {"timestamp": "2026-06-15", "event_type": "login_success", "username": "user1"}
        ]).encode("utf-8")
        
        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.AUDIT_LOGS.value},
            files={"file": ("audit.json", json_data, "application/json")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["chunks_ingested"] == 2

    @patch("pypdf.PdfReader")
    def test_pdf_upload(self, mock_pdf_reader, auth_headers):
        # Mocking PdfReader structure
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is a compliance document content"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader

        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.COMPLIANCE_RECORDS.value},
            files={"file": ("report.pdf", b"fake pdf bytes", "application/pdf")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["chunks_ingested"] > 0
        mock_pdf_reader.assert_called_once()

    @patch("docx.Document")
    def test_docx_upload(self, mock_docx_document, auth_headers):
        # Mocking python-docx Document structure
        mock_paragraph = MagicMock()
        mock_paragraph.text = "This is paragraph content from word file."
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_paragraph]
        mock_docx_document.return_value = mock_doc

        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.PUBLIC_POLICIES.value},
            files={"file": ("guide.docx", b"fake docx bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["chunks_ingested"] > 0
        mock_docx_document.assert_called_once()

    @patch("openpyxl.load_workbook")
    def test_excel_upload(self, mock_load_workbook, auth_headers):
        # Mocking openpyxl workbook structure
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

        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.SALARY_RECORDS.value},
            files={"file": ("salaries.xlsx", b"fake excel bytes", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert response.status_code == status.HTTP_200_OK
        # 2 rows (excluding header) = 2 chunks
        assert response.json()["chunks_ingested"] == 2
        mock_load_workbook.assert_called_once()

    @patch("PIL.Image.open")
    def test_image_upload(self, mock_image_open, auth_headers):
        # Mocking PIL Image structure
        mock_image = MagicMock()
        mock_image.format = "JPEG"
        mock_image.width = 1024
        mock_image.height = 768
        mock_image.mode = "RGB"
        # Mocking EXIF data tag dict: 271 is Make, 272 is Model
        mock_image._getexif.return_value = {271: b"Canon", 272: b"EOS 5D"}
        mock_image_open.return_value = mock_image

        response = client.post(
            "/api/v1/document/upload",
            headers=auth_headers["admin"],
            data={"data_source": DataSource.INFRASTRUCTURE_REPORTS.value},
            files={"file": ("datacenter.jpg", b"fake image bytes", "image/jpeg")},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["chunks_ingested"] > 0
        mock_image_open.assert_called_once()
