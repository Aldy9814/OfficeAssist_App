import os
import json
import re
import time
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from services.wa_client import ConsoleClient

log = logging.getLogger("broadcast")
_engine = None

ALL_KEYWORDS = {"all", "semua", "semua karyawan", "all employees", "*"}
PREFIXES = ("divisi:", "division:", "div:", "karywan:", "employee:")

def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        _engine = create_engine(os.getenv("DATABASE_URL"))
    return _engine

def clean_phone(raw) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits
