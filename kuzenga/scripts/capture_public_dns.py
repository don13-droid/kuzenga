"""Capture public DNS evidence without mailbox credentials or DNS changes."""

import json
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

QUERIES = [
    ("elevondigitalzw.com", "NS"),
    ("elevondigitalzw.com", "A"),
    ("elevondigitalzw.com", "AAAA"),
    ("www.elevondigitalzw.com", "A"),
    ("www.elevondigitalzw.com", "AAAA"),
    ("www.elevondigitalzw.com", "CNAME"),
    ("elevondigitalzw.com", "MX"),
    ("elevondigitalzw.com", "TXT"),
    ("_dmarc.elevondigitalzw.com", "TXT"),
]


def main():
    # Evidence capture is not a passing assertion about DNS or mailbox readiness.
    # Mailbox activation and real delivery require separate authenticated tests.
    for name, record_type in QUERIES:
        request = Request(
            "https://dns.google/resolve?" + urlencode({"name": name, "type": record_type}),
            headers={"Accept": "application/dns-json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                data = json.load(response)
            result = {
                "name": name,
                "type": record_type,
                "dns_status": data.get("Status"),
                "answers": data.get("Answer", []),
                "status": "OBSERVED",
            }
        except (URLError, TimeoutError, ValueError) as exc:
            result = {
                "name": name, "type": record_type,
                "status": "BLOCKED", "error_type": type(exc).__name__,
            }
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
