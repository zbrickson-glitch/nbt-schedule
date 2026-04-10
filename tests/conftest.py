import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

@pytest.fixture
def schedule_monday_pdf():
    return os.path.join(FIXTURES_DIR, "schedule-monday-3-2.pdf")

@pytest.fixture
def schedule_thursday_pdf():
    return os.path.join(FIXTURES_DIR, "schedule-thursday-2-26.pdf")

@pytest.fixture
def schedule_friday_pdf():
    return os.path.join(FIXTURES_DIR, "schedule-friday-2-27.pdf")

@pytest.fixture
def company_b_rr_pdf():
    return os.path.join(FIXTURES_DIR, "company-b-rr.pdf")

@pytest.fixture
def zigzag_rr_pdf():
    return os.path.join(FIXTURES_DIR, "zigzag-rr-sections.pdf")

@pytest.fixture
def dec10_pdf():
    return os.path.join(FIXTURES_DIR, "pdfs", "dec10_schedule.pdf")

@pytest.fixture
def dec26_pdf():
    return os.path.join(FIXTURES_DIR, "pdfs", "dec26_schedule.pdf")
