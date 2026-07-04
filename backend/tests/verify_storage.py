"""Verify Supabase Storage upload/download/delete (run from backend/: python -m tests.verify_storage).

Reads credentials from backend/.env. No secrets in this file.
"""
import sys
import uuid

from app.services import storage

ok = True


def check(label: str, condition: bool, extra: str = ""):
    global ok
    print(("PASS" if condition else "FAIL"), label, extra)
    ok = ok and condition


path = f"_verify/{uuid.uuid4()}.pdf"
payload = b"%PDF-1.4 fake bytes for storage round-trip"

try:
    storage.upload_pdf(path, payload)
    check("upload_pdf", True)
except Exception as exc:  # noqa: BLE001
    check("upload_pdf", False, str(exc)[:200])

try:
    fetched = storage.download(path)
    check("download round-trips", fetched == payload, f"got {len(fetched)} bytes")
except Exception as exc:  # noqa: BLE001
    check("download round-trips", False, str(exc)[:200])

try:
    storage.delete([path])
    check("delete", True)
except Exception as exc:  # noqa: BLE001
    check("delete", False, str(exc)[:200])

print()
print("STORAGE VERIFICATION:", "ALL PASS" if ok else "FAILURES - see above")
sys.exit(0 if ok else 1)
