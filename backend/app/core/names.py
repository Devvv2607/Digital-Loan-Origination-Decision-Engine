"""Name normalisation and fuzzy matching (EC-04 and fraud check F3; threshold in F3 policy).

Similarity is a token-sort ratio in [0, 1]: case, punctuation, extra spaces and
word order are ignored, so "VERMA, Asha" matches "Asha Verma" exactly.
"""

import re
from difflib import SequenceMatcher


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z ]+", " ", name).upper()
    return " ".join(sorted(cleaned.split()))


def name_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return round(SequenceMatcher(None, na, nb).ratio(), 4)


def display_name(name: str) -> str:
    """'ASHA R VERMA' -> 'Asha R Verma' (for storing a PAN name as the applicant's name)."""
    return " ".join(part.capitalize() for part in name.split())
