"""PDF report generation.

This is a sales asset, not a debug dump. The consultant attaches it to their
first email, so it has to read like something a professional produced.

Every finding shows its evidence. That is the whole reason a prospect takes
the claim seriously instead of treating it as a cold-call gimmick.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import FindingStatus, Severity
from leadkhojo.core.utils.clock import iso, utcnow
from leadkhojo.pipeline.runner import BusinessResult

_SEVERITY_COLOR: dict[Severity, colors.Color] = {
    Severity.CRITICAL: colors.HexColor("#B3261E"),
    Severity.HIGH: colors.HexColor("#C4642B"),
    Severity.MEDIUM: colors.HexColor("#B08900"),
    Severity.LOW: colors.HexColor("#4A6FA5"),
    Severity.INFO: colors.HexColor("#5F6368"),
}

_INK = colors.HexColor("#1A1C1E")
_MUTED = colors.HexColor("#5F6368")
_RULE = colors.HexColor("#D8DCE0")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "LKTitle",
            parent=base["Title"],
            fontSize=24,
            leading=28,
            textColor=_INK,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "LKSubtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            textColor=_MUTED,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "LKH2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            textColor=_INK,
            spaceBefore=16,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "LKH3",
            parent=base["Heading3"],
            fontSize=11,
            leading=14,
            textColor=_INK,
            spaceBefore=10,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "LKBody",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13.5,
            textColor=_INK,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "LKSmall",
            parent=base["Normal"],
            fontSize=8,
            leading=11,
            textColor=_MUTED,
        ),
        "evidence": ParagraphStyle(
            "LKEvidence",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=7.5,
            leading=10,
            textColor=_MUTED,
            leftIndent=8,
        ),
    }


def _escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hex(colour: colors.Color) -> str:
    """ReportLab paragraph markup needs #rrggbb, not the 0x-prefixed hexval()."""
    return f"#{int(colour.red * 255):02X}{int(colour.green * 255):02X}{int(colour.blue * 255):02X}"


def _urgency_colour(urgency: str) -> colors.Color:
    return {
        "critical": _SEVERITY_COLOR[Severity.CRITICAL],
        "high": _SEVERITY_COLOR[Severity.HIGH],
        "medium": _SEVERITY_COLOR[Severity.MEDIUM],
        "low": _SEVERITY_COLOR[Severity.LOW],
    }.get(urgency, _MUTED)


def _score_table(result: BusinessResult, styles: dict[str, ParagraphStyle]) -> Table:
    scores = result.scores
    values = (
        [
            str(scores.lead.total),
            str(scores.website.total),
            str(scores.security.total),
            str(scores.opportunity.total),
        ]
        if scores
        else ["-", "-", "-", "-"]
    )
    data = [
        ["LEAD QUALITY", "WEBSITE", "SECURITY", "OPPORTUNITY"],
        values,
    ]
    table = Table(data, colWidths=[42 * mm] * 4)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 7),
                ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 22),
                ("TEXTCOLOR", (0, 1), (-1, 1), _INK),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("BOX", (0, 0), (-1, -1), 0.5, _RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, _RULE),
            ]
        )
    )
    return table


def _finding_block(finding: Finding, styles: dict[str, ParagraphStyle]) -> KeepTogether:
    colour = _SEVERITY_COLOR.get(finding.severity, _MUTED)
    heading = (
        f'<font color="{_hex(colour)}"><b>[{finding.severity.value.upper()}]</b></font> '
        f"<b>{_escape(finding.title)}</b>"
    )
    parts = [
        Paragraph(heading, styles["h3"]),
        Paragraph(_escape(finding.description), styles["body"]),
    ]

    if finding.evidence:
        rows = "<br/>".join(
            f"{_escape(k)}: {_escape(v)}"
            for k, v in list(finding.evidence.items())[:6]
            if not isinstance(v, (dict, list))
        )
        if rows:
            parts.append(Paragraph(f"<b>Evidence</b><br/>{rows}", styles["evidence"]))

    if finding.remediation:
        parts.append(
            Paragraph(f"<b>Recommended fix:</b> {_escape(finding.remediation)}", styles["small"])
        )

    parts.append(Spacer(1, 6))
    return KeepTogether(parts)


def build_business_report(result: BusinessResult) -> bytes:
    """One business, full detail. This is the file that gets emailed."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Website Intelligence Report - {result.business.name}",
        author="LeadKhojo",
    )

    story: list[object] = []
    business = result.business

    story.append(Paragraph(_escape(business.name), styles["title"]))
    story.append(
        Paragraph(
            f"{_escape(business.website_url or business.domain or '')} &nbsp;&middot;&nbsp; "
            f"Analyzed {iso(result.snapshot.captured_at) if result.snapshot else iso(utcnow())}",
            styles["subtitle"],
        )
    )
    story.append(_score_table(result, styles))
    story.append(Spacer(1, 10))

    if not result.ok:
        story.append(Paragraph("Analysis incomplete", styles["h2"]))
        reason = result.failure_reason.value if result.failure_reason else "unknown"
        story.append(
            Paragraph(
                f"The site could not be fully analyzed ({_escape(reason)}). "
                f"{_escape(result.error or '')}",
                styles["body"],
            )
        )
        doc.build(story)
        return buffer.getvalue()

    # -- opportunities: what the reader actually cares about ---------------
    if result.opportunities:
        story.append(Paragraph("Opportunities", styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE, spaceAfter=8))
        for opportunity in result.opportunities:
            colour = _urgency_colour(opportunity.urgency.value)
            story.append(
                KeepTogether(
                    [
                        Paragraph(
                            f'<font color="{_hex(colour)}"><b>'
                            f"[{opportunity.urgency.value.upper()}]</b></font> "
                            f"<b>{_escape(opportunity.title)}</b>",
                            styles["h3"],
                        ),
                        Paragraph(_escape(opportunity.display_description), styles["body"]),
                        Spacer(1, 6),
                    ]
                )
            )

    # -- contacts ----------------------------------------------------------
    contacts = result.artifact("contacts", "contacts", []) or []
    story.append(Paragraph("Contact details", styles["h2"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE, spaceAfter=8))
    if contacts:
        rows = [["Type", "Value", "Found on"]]
        for contact in contacts[:12]:
            rows.append(
                [
                    str(contact.get("category", "")),
                    str(contact.get("value", ""))[:48],
                    str(contact.get("source_url", ""))[:44],
                ]
            )
        table = Table(rows, colWidths=[24 * mm, 68 * mm, 76 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, _RULE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)
    else:
        story.append(
            Paragraph(
                "No business contact details were published on the pages analyzed. "
                "LeadKhojo does not guess addresses, so this is a real result.",
                styles["body"],
            )
        )

    # -- technology --------------------------------------------------------
    technologies = result.artifact("technologies", "technologies", []) or []
    if technologies:
        story.append(Paragraph("Technology", styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE, spaceAfter=8))
        rows = [["Technology", "Category", "Version"]]
        for tech in technologies[:20]:
            rows.append(
                [
                    str(tech.get("name", "")),
                    str(tech.get("category", "")),
                    str(tech.get("version") or "-")
                    + (" (outdated)" if tech.get("is_outdated") else ""),
                ]
            )
        table = Table(rows, colWidths=[62 * mm, 50 * mm, 56 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, _RULE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)

    # -- findings ----------------------------------------------------------
    problems = [f for f in result.findings if f.status in (FindingStatus.FAIL, FindingStatus.WARN)]
    if problems:
        story.append(PageBreak())
        story.append(Paragraph("Technical findings", styles["h2"]))
        story.append(
            Paragraph(
                "Every finding below includes the evidence it was based on, so each "
                "one can be verified independently.",
                styles["small"],
            )
        )
        story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE, spaceAfter=8))
        for finding in problems:
            story.append(_finding_block(finding, styles))

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Generated by LeadKhojo from publicly available information published by "
            "the website itself. All checks are passive: ordinary page requests, "
            "public DNS lookups and a standard TLS handshake. No scanning or probing "
            "was performed.",
            styles["small"],
        )
    )

    doc.build(story)
    return buffer.getvalue()


def build_scan_summary(results: Sequence[BusinessResult], *, title: str = "Scan summary") -> bytes:
    """All businesses, ranked. The overview a user works through."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="LeadKhojo",
    )

    ok = [r for r in results if r.ok]
    ranked = sorted(ok, key=lambda r: r.scores.opportunity.total if r.scores else 0, reverse=True)

    story: list[object] = [
        Paragraph(_escape(title), styles["title"]),
        Paragraph(
            f"{len(ok)} of {len(results)} businesses analyzed &middot; "
            f"{sum(len(r.opportunities) for r in ok)} opportunities identified &middot; "
            f"generated {iso(utcnow())}",
            styles["subtitle"],
        ),
    ]

    rows = [["#", "Business", "Opp", "Sec", "Lead", "Contact", "Top opportunity"]]
    for index, result in enumerate(ranked, start=1):
        scores = result.scores
        rows.append(
            [
                str(index),
                str(result.business.name)[:26],
                str(scores.opportunity.total) if scores else "-",
                str(scores.security.total) if scores else "-",
                str(scores.lead.total) if scores else "-",
                str(result.artifact("contacts", "primary_email") or "-")[:28],
                str(result.opportunities[0].title if result.opportunities else "-")[:34],
            ]
        )

    table = Table(
        rows,
        colWidths=[8 * mm, 40 * mm, 12 * mm, 12 * mm, 12 * mm, 46 * mm, 50 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8F9")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_business_report", "build_scan_summary"]
