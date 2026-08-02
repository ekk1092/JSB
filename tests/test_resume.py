import json
import os
from unittest.mock import patch

from docx import Document

from server.tools.resume import (
    sanitize_filename,
    create_resume_docx,
    create_cover_letter_docx,
    extract_job_metadata,
    _METADATA_CACHE,
)


def test_sanitize_filename():
    assert sanitize_filename("John Doe") == "John_Doe"
    assert sanitize_filename("Acme, Inc.") == "Acme_Inc"
    # Leading/trailing spaces trimmed; internal spaces become underscores
    assert sanitize_filename("  spaced  out  ") == "spaced__out"
    assert sanitize_filename("") == ""


def test_create_resume_docx():
    data = {
        "name": "Jane Smith",
        "contact": {"email": "jane@example.com", "phone": "555-1234"},
        "summary": "Experienced engineer.",
        "experience": [
            {
                "title": "Engineer",
                "company": "Acme",
                "location": "NYC",
                "dates": "2020-2023",
                "responsibilities": ["Built things", "Fixed things"],
            }
        ],
        "education": [{"degree": "BS", "school": "UNCW", "location": "NC", "graduation": "2020"}],
        "skills": ["Python", "AWS"],
    }
    path = create_resume_docx(data)
    try:
        assert os.path.exists(path)
        assert path.endswith(".docx")
        doc = Document(path)
        # Name should be present
        texts = [p.text for p in doc.paragraphs]
        assert "Jane Smith" in texts
        assert "PROFESSIONAL SUMMARY" in texts
        assert "EXPERIENCE" in texts
        assert "SKILLS" in texts
    finally:
        os.unlink(path)


def test_create_cover_letter_docx():
    data = {
        "name": "Jane Smith",
        "contact": {"email": "jane@example.com", "phone": "555-1234"},
        "date": "August 2, 2026",
        "recipient": {"name": "Hiring Manager", "company": "Acme", "address": "NYC"},
        "body_paragraphs": ["Para one.", "Para two."],
    }
    path = create_cover_letter_docx(data)
    try:
        assert os.path.exists(path)
        assert path.endswith(".docx")
        doc = Document(path)
        texts = [p.text for p in doc.paragraphs]
        assert "Jane Smith" in texts
        assert "Acme" in texts
        assert "Sincerely," in texts
    finally:
        os.unlink(path)


def test_extract_job_metadata_caches_result():
    """extract_job_metadata should cache results per job description."""
    _METADATA_CACHE.clear()

    fake_response = type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '{"company_name": "Acme", "company_location": "NYC"}'})()})()]})()
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": type("Comp", (), {"create": lambda self, **kw: fake_response})()})()})()

    with patch("server.tools.resume.get_azure_client", return_value=fake_client):
        meta1 = extract_job_metadata("Job description for Acme in NYC")
        meta2 = extract_job_metadata("Job description for Acme in NYC")

    assert meta1 == {"company_name": "Acme", "company_location": "NYC"}
    assert meta2 == meta1
    # Cache should have exactly one entry (second call hit cache)
    assert len(_METADATA_CACHE) == 1