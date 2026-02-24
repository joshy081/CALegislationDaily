"""CA Legislation Daily Email Service

Cloud Run service that fetches California legislative changes from LegiScan,
identifies bills with recent activity, and returns email-ready JSON for
Zapier to send.

Endpoint: GET /?days=1&format=email
"""

import html
import os
from datetime import datetime, timedelta, timezone

import functions_framework
import requests
from flask import jsonify, request

# --- Configuration ---

LEGISCAN_API_KEY = os.environ.get("LEGISCAN_API_KEY", "")
LEGISCAN_BASE_URL = "https://api.legiscan.com/"
CA_STATE_CODE = "CA"

BILL_STATUS = {
    1: "Introduced",
    2: "Engrossed",
    3: "Enrolled",
    4: "Passed",
    5: "Vetoed",
    6: "Failed/Dead",
}

# --- LegiScan API helpers ---


def legiscan_request(op, **params):
    """Make a request to the LegiScan API."""
    params["key"] = LEGISCAN_API_KEY
    params["op"] = op
    resp = requests.get(LEGISCAN_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "ERROR":
        alert = data.get("alert", {})
        msg = alert.get("message", "Unknown error") if isinstance(alert, dict) else str(alert)
        raise requests.RequestException(f"LegiScan API error: {msg}")
    return data


def fetch_master_list():
    """Fetch the master list of all CA bills in the current session."""
    data = legiscan_request("getMasterList", state=CA_STATE_CODE)
    return data.get("masterlist", {})


def fetch_bill_detail(bill_id):
    """Fetch full detail for a single bill."""
    data = legiscan_request("getBill", id=bill_id)
    return data.get("bill", {})


def filter_bills_by_date(master_list, days=1):
    """Filter master list to bills with activity in the last N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    changed_bills = []
    for key, bill in master_list.items():
        if key == "session":
            continue
        if not isinstance(bill, dict):
            continue
        last_action_date = bill.get("last_action_date", "")
        if last_action_date >= cutoff:
            changed_bills.append(bill)
    return changed_bills


# --- Formatting helpers ---


def format_status(status_code):
    """Convert numeric bill status to human-readable text."""
    return BILL_STATUS.get(status_code, f"Status {status_code}")


def format_sponsors(sponsors):
    """Format sponsor list into readable string."""
    if not sponsors:
        return "No sponsors listed"
    parts = []
    for s in sponsors:
        name = s.get("name", "Unknown")
        party = s.get("party", "")
        entry = name
        if party:
            entry += f" ({party})"
        parts.append(entry)
    return ", ".join(parts)


def get_latest_history_action(history):
    """Extract the most recent legislative action from bill history."""
    if not history:
        return "No actions recorded"
    latest = history[-1]
    return latest.get("action", "No action text")


def get_bill_text_url(bill_detail):
    """Get URL to the most recent bill text."""
    texts = bill_detail.get("texts", [])
    if not texts:
        return ""
    latest_text = texts[-1]
    return latest_text.get("state_link", "") or latest_text.get("url", "")


# --- Email formatting ---


def format_email_subject(bill_number, title, status):
    """Format the email subject line."""
    max_title_len = 60
    short_title = title[:max_title_len] + "..." if len(title) > max_title_len else title
    return f"{bill_number}: {short_title} [{status}]"


def format_email_body(bill_number, title, description, status, last_action,
                      last_action_date, sponsors_text, bill_url, text_url):
    """Format the email body as HTML."""
    text_link_html = ""
    if text_url:
        text_link_html = f"""
<p><a href="{html.escape(text_url)}" style="color: #1a5276;">Read Full Bill Text</a></p>"""

    bill_link_html = ""
    if bill_url:
        bill_link_html = f"""
<p><a href="{html.escape(bill_url)}" style="color: #1a5276;">View on LegiScan</a></p>"""

    return f"""<div style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #1a1a1a;">{html.escape(bill_number)}: {html.escape(title)}</h2>
<p style="color: #666; font-size: 14px;">
    Status: {html.escape(status)} | Last Action: {html.escape(last_action_date)} | Sponsors: {html.escape(sponsors_text)}
</p>
<hr>
<p><strong>Description:</strong></p>
<p>{html.escape(description)}</p>
<hr>
<p><strong>Latest Action:</strong></p>
<p>{html.escape(last_action)}</p>
{text_link_html}
{bill_link_html}
<hr>
<p style="font-size: 12px; color: #999;">
    California Legislature &mdash; {html.escape(bill_number)}<br>
    Source: LegiScan
</p>
</div>"""


# --- Main handler ---


def process_bills(days=1):
    """Fetch and process CA bills with recent activity."""
    master_list = fetch_master_list()
    changed_bills = filter_bills_by_date(master_list, days=days)
    bills = []

    for bill_summary in changed_bills:
        bill_id = bill_summary.get("bill_id")
        if not bill_id:
            continue

        try:
            detail = fetch_bill_detail(bill_id)
        except requests.RequestException:
            continue

        bill_number = detail.get("bill_number", bill_summary.get("number", "Unknown"))
        title = detail.get("title", "")
        description = detail.get("description", "")
        status_code = detail.get("status", bill_summary.get("status", 0))
        status_text = format_status(status_code)
        last_action_date = bill_summary.get("last_action_date", "")
        last_action = bill_summary.get("last_action", "")

        history = detail.get("history", [])
        if history:
            last_action = get_latest_history_action(history)

        sponsors = detail.get("sponsors", [])
        sponsors_text = format_sponsors(sponsors)
        bill_url = detail.get("url", bill_summary.get("url", ""))
        text_url = get_bill_text_url(detail)

        bill = {
            "bill_id": bill_id,
            "bill_number": bill_number,
            "title": title,
            "description": description,
            "status": status_text,
            "status_code": status_code,
            "last_action": last_action,
            "last_action_date": last_action_date,
            "sponsors": sponsors_text,
            "bill_url": bill_url,
            "text_url": text_url,
            "external_id": f"LS-{bill_id}",
            "email_subject": format_email_subject(bill_number, title, status_text),
            "email_body": format_email_body(
                bill_number, title, description, status_text, last_action,
                last_action_date, sponsors_text, bill_url, text_url,
            ),
        }
        bills.append(bill)

    bills.sort(key=lambda b: b.get("bill_number", ""))
    return bills


@functions_framework.http
def ca_legislation_daily(request):
    """HTTP Cloud Function entry point.

    Query params:
        days (int): Number of days to look back (default 1)
        format (str): Response format — "email" for Zapier-ready JSON (default "email")
    """
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    days = request.args.get("days", 1, type=int)
    fmt = request.args.get("format", "email")

    try:
        bills = process_bills(days=days)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return jsonify({"error": "Rate limited by LegiScan. Try again later."}), 429
        return jsonify({"error": f"LegiScan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Internal error: {str(e)}"}), 500

    response_data = {
        "count": len(bills),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "bills": bills,
    }

    resp = jsonify(response_data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
