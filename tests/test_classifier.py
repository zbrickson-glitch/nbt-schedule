import pathlib

from app.parsers.classifier import classify_pdf, classify_email, PdfType, EmailType

def test_classify_daily_schedule():
    assert classify_pdf("Monday 3.2.26 Artist Daily Schedule.pdf") == PdfType.SCHEDULE
    assert classify_pdf("Thursday 2.26.26 Artist Daily Schedule.pdf") == PdfType.SCHEDULE
    assert classify_pdf("Friday 2.27.26 Artist Daily Schedule.pdf") == PdfType.SCHEDULE

def test_classify_role_responsibilities():
    assert classify_pdf("Company B RR 2.17.2026.pdf") == PdfType.CASTING
    assert classify_pdf("ZigZag sections RR 2.13.26.pdf") == PdfType.CASTING
    assert classify_pdf("ZigZag RR 2026 2.4.26.pdf") == PdfType.CASTING
    assert classify_pdf("Revised ZigZag Role Responsibilities.pdf") == PdfType.CASTING

def test_classify_unknown():
    assert classify_pdf("random-file.pdf") == PdfType.UNKNOWN

def test_classify_email_cast_change():
    assert classify_email(
        subject="Cast Change",
        body="Isaac Aguirre will perform Zachary Brickson's role",
        attachments=[]
    ) == EmailType.CAST_CHANGE

def test_classify_email_mixed():
    assert classify_email(
        subject="Artistic Schedule for Monday, 2/9 and ZigZag role responsibilities",
        body="",
        attachments=["Monday 2.9.26 Artist Daily Schedule.pdf", "ZigZag RR 2026 2.4.26.pdf"]
    ) == EmailType.MIXED

def test_classify_email_schedule_only():
    assert classify_email(
        subject="Monday, 3/2 Artist Daily Schedule",
        body="",
        attachments=["Monday 3.2.26 Artist Daily Schedule.pdf"]
    ) == EmailType.SCHEDULE

def test_classify_email_casting_only():
    assert classify_email(
        subject="Revised Company B Role Responsibilities",
        body="",
        attachments=["Company B RR 2.17.2026.pdf"]
    ) == EmailType.CASTING

def test_artistic_schedule_variants():
    # All real Brooke filename variants must be classified as SCHEDULE
    assert classify_pdf("Tuesday, 12.16.25 Artistic Daily Schedule.pdf") == PdfType.SCHEDULE
    assert classify_pdf("Artistic Schedule for Sat Sun December 20-21.pdf") == PdfType.SCHEDULE
    assert classify_pdf("Thursday and Friday 12-18 - 19 Artistic Schedule.pdf") == PdfType.SCHEDULE

def test_classify_maag():
    assert classify_pdf("February Month at a Glance.pdf") == PdfType.MAAG
    assert classify_pdf("MAAG March 2026.pdf") == PdfType.MAAG
    assert classify_pdf("Monthly Calendar Overview.pdf") == PdfType.MAAG

def test_classify_email_cancellation():
    assert classify_email(
        subject="Tico Tico 11:15am rehearsal today cancelled",
        body="Please be advised that the 11:15am rehearsal today for Tico Tico has been cancelled.",
        attachments=[]
    ) == EmailType.CANCELLATION

def test_classify_email_cancellation_performance():
    assert classify_email(
        subject="CANCELLATION OF TODAY'S PERFORMANCE",
        body="April 20 at 2pm Peter Pan Matinee has been cancelled",
        attachments=[]
    ) == EmailType.CANCELLATION

def test_classify_email_emergency():
    assert classify_email(
        subject="EMERGENCY Rehearsal at 6:30pm tonight",
        body="All Pirates, Lost Boys and James Hook are needed for an EMERGENCY REHEARSAL today at 6:30pm on stage.",
        attachments=[]
    ) == EmailType.EMERGENCY

def test_classify_email_additional_detail():
    assert classify_email(
        subject="Additional Detail for Friday, 12/12",
        body="Please see the additional detail below regarding Friday, 12/12 scheduled rehearsals",
        attachments=[]
    ) == EmailType.ADDITIONAL_DETAIL

def test_classify_email_unknown_body_only():
    """Body-text emails that don't match any pattern should be UNKNOWN."""
    assert classify_email(
        subject="Reminder about parking",
        body="Please remember to park in the correct spots",
        attachments=[]
    ) == EmailType.UNKNOWN

def test_email_with_attachments_ignores_body_keywords():
    """Attachment-based classification takes priority over body keywords.
    Even if subject/body say 'cancelled', a schedule PDF attachment wins."""
    assert classify_email(
        subject="cancelled rehearsal",
        body="The rehearsal has been cancelled",
        attachments=["Monday 3.2.26 Artist Daily Schedule.pdf"]
    ) == EmailType.SCHEDULE

def test_maag_filename_case_insensitive():
    """MAAG_PATTERNS use (?i) flag — matching must be case-insensitive."""
    assert classify_pdf("MONTH AT A GLANCE.pdf") == PdfType.MAAG
    assert classify_pdf("month at a glance.pdf") == PdfType.MAAG

def test_cancellation_in_body_not_subject():
    """'cancel' in the body text (not subject) should still trigger CANCELLATION.
    classify_email combines subject + body into a single 'text' string."""
    assert classify_email(
        subject="Update",
        body="the rehearsal has been cancelled",
        attachments=[]
    ) == EmailType.CANCELLATION

def test_emergency_without_rehearsal_not_emergency():
    """EMERGENCY requires BOTH 'emergency' AND 'rehearsal' in the combined text.
    'emergency contact' without 'rehearsal' must NOT classify as EMERGENCY."""
    result = classify_email(
        subject="EMERGENCY contact info",
        body="Please update your emergency contact",
        attachments=[]
    )
    assert result != EmailType.EMERGENCY

def test_cancellation_variants():
    """Both American ('canceled') and British ('cancelled') spellings, plus
    'CANCELLATION' in subject, must all trigger CANCELLATION (all contain 'cancel')."""
    assert classify_email(
        subject="Rehearsal canceled today",
        body="",
        attachments=[]
    ) == EmailType.CANCELLATION
    assert classify_email(
        subject="Rehearsal cancelled today",
        body="",
        attachments=[]
    ) == EmailType.CANCELLATION
    assert classify_email(
        subject="CANCELLATION of rehearsal",
        body="",
        attachments=[]
    ) == EmailType.CANCELLATION

def test_additional_detail_only_in_subject():
    """'additional detail' must appear in the SUBJECT to trigger ADDITIONAL_DETAIL.
    The code checks `subject.lower()` specifically, not the combined text."""
    # Should match when in subject
    assert classify_email(
        subject="Additional Detail for Friday",
        body="no additional detail in body",
        attachments=[]
    ) == EmailType.ADDITIONAL_DETAIL
    # Should NOT match when only in body (subject is neutral, no other trigger matches)
    result = classify_email(
        subject="Friday rehearsal notes",
        body="Here is some additional detail about the rehearsal",
        attachments=[]
    )
    assert result != EmailType.ADDITIONAL_DETAIL

def test_empty_subject_and_body():
    """Empty subject and body with no attachments should return UNKNOWN."""
    assert classify_email(
        subject="",
        body="",
        attachments=[]
    ) == EmailType.UNKNOWN

def test_schedule_pdf_with_cancel_in_body():
    """A schedule PDF attachment + 'cancelled' in body must return SCHEDULE.
    Attachment classification dominates; body keywords are ignored when
    attachments are present."""
    assert classify_email(
        subject="Today's schedule",
        body="Note: one block has been cancelled but see attached schedule",
        attachments=["Tuesday 3.3.26 Artist Daily Schedule.pdf"]
    ) == EmailType.SCHEDULE

def test_maag_takes_priority_over_schedule():
    """classify_pdf checks MAAG patterns before SCHEDULE patterns.
    A filename matching both (e.g., contains 'Month at a Glance' AND 'Schedule')
    must return MAAG."""
    assert classify_pdf("February Month at a Glance Schedule.pdf") == PdfType.MAAG

def test_classify_pdf_non_pdf_extension():
    """classify_pdf matches on filename string content, not file extension.
    A .docx filename containing a schedule keyword still matches SCHEDULE_PATTERNS."""
    assert classify_pdf("schedule.docx") == PdfType.SCHEDULE


def test_classify_pdf_unknown_filename_still_unknown_without_bytes():
    """Filename with no keyword returns UNKNOWN when no bytes provided."""
    assert classify_pdf("NBT Spring 2026.pdf") == PdfType.UNKNOWN


def test_classify_pdf_with_bytes_detects_schedule(schedule_monday_pdf):
    """When filename has no keyword but PDF content shows schedule table, classify as SCHEDULE."""
    pdf_bytes = pathlib.Path(schedule_monday_pdf).read_bytes()
    result = classify_pdf("unknown_filename.pdf", pdf_bytes=pdf_bytes)
    assert result == PdfType.SCHEDULE
