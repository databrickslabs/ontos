"""
Generate an HTML agreement document from wizard session data.

Used as the primary PDF generation strategy (no external dependencies).
The HTML document is styled for print and can be saved as PDF via the browser.
When reportlab is available, the existing agreement_pdf.py in common/ is used instead.
"""

import json
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger

logger = get_logger(__name__)


def build_agreement_html(
    workflow_name: str,
    entity_type: str,
    entity_id: str,
    step_results: List[Dict[str, Any]],
    snapshot: Optional[str] = None,
    created_by: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> str:
    """Build an HTML document summarizing the agreement.

    Args:
        workflow_name: Name of the approval workflow.
        entity_type: Entity type (e.g. data_product, dataset).
        entity_id: Entity identifier.
        step_results: List of { step_id, payload } dicts from the wizard session.
        snapshot: JSON string of the workflow snapshot (contains steps metadata).
        created_by: Email/username of the signer.
        created_at: Timestamp when the agreement was created.

    Returns:
        A complete HTML document string suitable for rendering or print-to-PDF.
    """
    snapshot_data = json.loads(snapshot) if snapshot else {}
    steps = snapshot_data.get("steps", [])

    e = escape  # shorthand
    ts = created_at.strftime("%Y-%m-%d %H:%M UTC") if created_at else "Unknown"

    html_parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        f"<title>Agreement - {e(workflow_name)}</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "max-width: 800px; margin: 40px auto; padding: 20px; color: #1a1a1a; }",
        "h1 { color: #1e40af; border-bottom: 2px solid #1e40af; padding-bottom: 8px; }",
        "h2 { color: #374151; margin-top: 24px; }",
        ".meta { color: #6b7280; font-size: 14px; margin-bottom: 24px; }",
        ".step { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; "
        "padding: 16px; margin: 12px 0; }",
        ".step-title { font-weight: 600; margin-bottom: 8px; }",
        ".field { margin: 4px 0; }",
        ".field-label { color: #6b7280; font-size: 13px; }",
        ".field-value { font-weight: 500; }",
        ".signature { margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; }",
        ".checkmark { color: #059669; }",
        ".crossmark { color: #dc2626; }",
        "@media print { body { margin: 0; } }",
        "</style>",
        "</head><body>",
        f"<h1>Agreement: {e(workflow_name)}</h1>",
        "<div class='meta'>",
        f"Entity: {e(entity_type)} / {e(entity_id)}<br>",
        f"Signed by: {e(created_by or 'Unknown')}<br>",
        f"Date: {e(ts)}",
        "</div>",
    ]

    # Render each step's results
    for i, sr in enumerate(step_results):
        step_id = sr.get("step_id", f"step-{i}")
        payload = sr.get("payload", {})
        # Find matching step in snapshot for metadata
        step_meta = next((s for s in steps if s.get("step_id") == step_id), {})
        step_name = step_meta.get("name", step_id)
        step_type = step_meta.get("step_type", "unknown")
        config = step_meta.get("config", {})

        html_parts.append("<div class='step'>")
        html_parts.append(f"<div class='step-title'>{e(step_name)}</div>")

        if step_type == "legal_document":
            ack = payload.get("acknowledged", False)
            mark_cls = "checkmark" if ack else "crossmark"
            mark_char = "\u2713" if ack else "\u2717"
            label = e(config.get("acknowledgement_label", "Acknowledged"))
            html_parts.append(
                f"<div class='field'><span class='{mark_cls}'>{mark_char}</span> {label}</div>"
            )

        elif step_type == "acknowledgement_checklist":
            items = config.get("items", [])
            checked = payload.get("items", {})
            for item in items:
                item_id = item.get("id", "")
                is_checked = checked.get(item_id, False)
                mark_cls = "checkmark" if is_checked else "crossmark"
                mark_char = "\u2713" if is_checked else "\u2717"
                label = e(item.get("label", ""))
                html_parts.append(
                    f"<div class='field'><span class='{mark_cls}'>{mark_char}</span> {label}</div>"
                )

        elif step_type == "co_signers":
            signers = payload.get("co_signers", [])
            if signers:
                html_parts.append(
                    "<div class='field'><span class='field-label'>Co-signers:</span></div>"
                )
                for s in signers:
                    html_parts.append(f"<div class='field'>&bull; {e(str(s))}</div>")
            else:
                html_parts.append(
                    "<div class='field'><span class='field-label'>No co-signers</span></div>"
                )

        elif step_type == "user_action":
            for key, value in payload.items():
                if isinstance(value, str) and value.strip():
                    label = e(key.replace("_", " ").title())
                    html_parts.append(
                        f"<div class='field'><span class='field-label'>{label}:</span> "
                        f"<span class='field-value'>{e(value)}</span></div>"
                    )

        else:
            # Generic fallback: show payload key/value pairs
            for key, value in payload.items():
                if isinstance(value, (str, int, float, bool)):
                    label = e(key.replace("_", " ").title())
                    html_parts.append(
                        f"<div class='field'><span class='field-label'>{label}:</span> "
                        f"<span class='field-value'>{e(str(value))}</span></div>"
                    )

        html_parts.append("</div>")

    # Signature block
    html_parts.extend([
        "<div class='signature'>",
        f"<strong>Digitally signed by:</strong> {e(created_by or 'Unknown')}<br>",
        f"<strong>Date:</strong> {e(ts)}<br>",
        f"<strong>Workflow:</strong> {e(workflow_name)}",
        "</div>",
        "</body></html>",
    ])

    return "\n".join(html_parts)
