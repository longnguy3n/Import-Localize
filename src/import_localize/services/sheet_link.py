"""Resolve shared Google Drive and Sheets links to the spreadsheet file ID."""
import re
from urllib.parse import parse_qs, urlsplit


def sheet_id_from_link(link: str) -> str | None:
    try:
        url = urlsplit(link.strip())
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            return None
        host = url.hostname
        if host == "docs.google.com":
            match = re.fullmatch(r"/spreadsheets/(?:u/\d+/)?d/([\w-]+)(?:/.*)?", url.path, re.ASCII)
        elif host == "drive.google.com":
            if url.path.rstrip("/") == "/open":
                ids = parse_qs(url.query).get("id", [])
                return ids[0] if len(ids) == 1 and re.fullmatch(r"[A-Za-z0-9_-]+", ids[0]) else None
            match = re.fullmatch(r"/file/d/([\w-]+)(?:/.*)?", url.path, re.ASCII)
        else:
            return None
        return match.group(1) if match else None
    except ValueError:
        return None
