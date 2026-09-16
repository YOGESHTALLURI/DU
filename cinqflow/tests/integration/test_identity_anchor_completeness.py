import itertools
from decimal import Decimal

# Scoring weights (positive only, as missing values contribute 0)
WEIGHTS = {
    "ssn": Decimal("40"),
    "dob": Decimal("25"),
    "last_name": Decimal("15"),
    "first_name": Decimal("10"),
    "gender": Decimal("5"),
    "postal": Decimal("5"),
}

THRESHOLD = Decimal("85")

def calculate_score(combo):
    return sum(WEIGHTS[attr] for attr in combo)

def test_anchor_completeness():
    attrs = list(WEIGHTS.keys())
    # Enumerate all non‑empty subsets of attributes
    for r in range(1, len(attrs) + 1):
        for combo in itertools.combinations(attrs, r):
            score = calculate_score(combo)
            if score > THRESHOLD:
                assert "ssn" in combo, (
                    f"High‑confidence combo {combo} (score={score}) lacks required 'ssn' anchor"
                )
