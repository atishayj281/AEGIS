"""Parser utilities for converting various file types to plain text chunks."""

import io
import csv
import json
from typing import Any


class DocumentParser:
    @staticmethod
    def parse_txt(file_bytes: bytes) -> str:
        """Parse plain text files."""
        return file_bytes.decode("utf-8", errors="ignore")

    @staticmethod
    def parse_pdf(file_bytes: bytes) -> str:
        """Parse PDF documents page-by-page."""
        from pypdf import PdfReader
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text_parts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n\n".join(text_parts)

    @staticmethod
    def parse_docx(file_bytes: bytes) -> str:
        """Parse Word documents paragraph-by-paragraph."""
        from docx import Document
        docx_file = io.BytesIO(file_bytes)
        doc = Document(docx_file)
        text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(text_parts)

    @staticmethod
    def parse_csv(file_bytes: bytes) -> list[str]:
        """Parse CSV rows and return them as textual strings."""
        text_content = file_bytes.decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text_content))
        chunks = []
        for i, row in enumerate(reader):
            row_str = ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
            chunks.append(f"Row {i+1}: {row_str}")
        return chunks

    @staticmethod
    def parse_excel(file_bytes: bytes) -> list[str]:
        """Parse Excel sheets and return rows as textual strings."""
        import openpyxl
        excel_file = io.BytesIO(file_bytes)
        # Using read_only=True and data_only=True for performance
        wb = openpyxl.load_workbook(excel_file, read_only=True, data_only=True)
        chunks = []
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            headers = []
            for r_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                if r_idx == 0:
                    headers = [str(cell) if cell is not None else f"Col{c_idx}" for c_idx, cell in enumerate(row)]
                    continue
                if not any(cell is not None for cell in row):
                    continue
                row_parts = []
                for c_idx, cell in enumerate(row):
                    if cell is not None:
                        header = headers[c_idx] if c_idx < len(headers) else f"Col{c_idx}"
                        row_parts.append(f"{header}: {cell}")
                if row_parts:
                    chunks.append(f"Sheet: {sheet_name}, Row {r_idx+1}: {', '.join(row_parts)}")
        return chunks

    @staticmethod
    def parse_json(file_bytes: bytes) -> list[str]:
        """Parse JSON objects or arrays and return text representation."""
        data = json.loads(file_bytes.decode("utf-8", errors="ignore"))
        chunks = []
        if isinstance(data, list):
            for i, entry in enumerate(data):
                if isinstance(entry, dict):
                    entry_str = ", ".join(f"{k}: {v}" for k, v in entry.items() if v is not None)
                    chunks.append(f"Record {i+1}: {entry_str}")
                else:
                    chunks.append(f"Record {i+1}: {entry}")
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    for i, item in enumerate(v):
                        chunks.append(f"Key {k}, Item {i+1}: {item}")
                else:
                    chunks.append(f"Key {k}: {v}")
        else:
            chunks.append(str(data))
        return chunks

    @staticmethod
    def parse_image(file_bytes: bytes, filename: str) -> str:
        """Parse image files and extract basic dimensions and EXIF metadata."""
        from PIL import Image
        img_file = io.BytesIO(file_bytes)
        img = Image.open(img_file)
        info = f"Image File: {filename}\nFormat: {img.format}\nDimensions: {img.width}x{img.height}\nMode: {img.mode}"
        
        exif_data = []
        if hasattr(img, "_getexif") and img._getexif():
            from PIL.ExifTags import TAGS
            exif = img._getexif()
            if exif:
                for tag, value in exif.items():
                    decoded = TAGS.get(tag, tag)
                    if decoded and value is not None:
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="ignore")[:100]
                        exif_data.append(f"{decoded}: {value}")
        if exif_data:
            info += "\nMetadata:\n" + "\n".join(exif_data)
        return info
