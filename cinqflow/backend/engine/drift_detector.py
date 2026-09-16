"""
Deterministic Pre-Ingestion Schema Drift Detector — Wave 2 Slice 1 (CF-V2-E5-04)

Detects structural discrepancies between landed file headers and active published SchemaContracts:
- Missing required fields (BREAKING)
- Missing optional fields (NON_BREAKING)
- Unexpected extra fields (NON_BREAKING)
- Delimiter deviations (BREAKING)
- Unparseable / empty / corrupted headers (BREAKING)

STRICT PRIVACY GUARANTEE:
Zero row/cell patient values are captured or persisted in drift reports.
Only field names, data type strings, and delimiter codes are inspected.
"""
import io
import csv
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from backend.models.drift import DriftSeverityEnum
from backend.models.schema import SchemaVersion


@dataclass
class DriftDetectionResult:
    drift_severity: DriftSeverityEnum
    missing_fields: List[str]
    missing_required: List[str]
    missing_optional: List[str]
    unexpected_fields: List[str]
    type_mismatches: List[Dict[str, Any]]
    detected_delimiter: Optional[str]
    summary: str


class SchemaDriftDetector:
    """
    Deterministic detector comparing landed raw bytes against published SchemaVersion.
    """

    @classmethod
    def detect_drift(
        cls,
        raw_bytes: bytes,
        schema_version: SchemaVersion,
        expected_delimiter: str = ",",
    ) -> DriftDetectionResult:
        if not raw_bytes or len(raw_bytes.strip()) == 0:
            return DriftDetectionResult(
                drift_severity=DriftSeverityEnum.BREAKING,
                missing_fields=[f.field_name for f in schema_version.fields if f.is_required],
                missing_required=[f.field_name for f in schema_version.fields if f.is_required],
                missing_optional=[f.field_name for f in schema_version.fields if not f.is_required],
                unexpected_fields=[],
                type_mismatches=[],
                detected_delimiter=None,
                summary="Empty or zero-byte file landed; header row missing",
            )

        # 1. Detect Encoding & Delimiter
        try:
            text_sample = raw_bytes[:4096].decode("utf-8-sig")
        except UnicodeDecodeError:
            return DriftDetectionResult(
                drift_severity=DriftSeverityEnum.BREAKING,
                missing_fields=[],
                missing_required=[],
                missing_optional=[],
                unexpected_fields=[],
                type_mismatches=[],
                detected_delimiter=None,
                summary="File bytes cannot be decoded as UTF-8; unparseable encoding",
            )

        first_line = text_sample.splitlines()[0] if text_sample.splitlines() else ""
        if not first_line.strip():
            return DriftDetectionResult(
                drift_severity=DriftSeverityEnum.BREAKING,
                missing_fields=[f.field_name for f in schema_version.fields if f.is_required],
                missing_required=[f.field_name for f in schema_version.fields if f.is_required],
                missing_optional=[],
                unexpected_fields=[],
                type_mismatches=[],
                detected_delimiter=None,
                summary="First line of landed file is empty; header row missing",
            )

        # Detect delimiter from candidate list: comma, tab, pipe, semicolon
        candidates = [",", "\t", "|", ";"]
        detected_delim = expected_delimiter
        counts = {c: first_line.count(c) for c in candidates}
        best_candidate = max(counts, key=counts.get)
        if counts[best_candidate] > 0:
            detected_delim = best_candidate

        # 2. Check Delimiter Mismatch
        delimiter_mismatch = (detected_delim != expected_delimiter)

        # 3. Parse Header Columns
        try:
            reader = csv.reader(io.StringIO(first_line), delimiter=detected_delim)
            header_cols = next(reader, [])
            header_cols_clean = [c.strip() for c in header_cols if c.strip()]
        except Exception as e:
            return DriftDetectionResult(
                drift_severity=DriftSeverityEnum.BREAKING,
                missing_fields=[],
                missing_required=[],
                missing_optional=[],
                unexpected_fields=[],
                type_mismatches=[],
                detected_delimiter=detected_delim,
                summary=f"Failed to parse header row: {str(e)}",
            )

        if not header_cols_clean:
            return DriftDetectionResult(
                drift_severity=DriftSeverityEnum.BREAKING,
                missing_fields=[f.field_name for f in schema_version.fields if f.is_required],
                missing_required=[f.field_name for f in schema_version.fields if f.is_required],
                missing_optional=[],
                unexpected_fields=[],
                type_mismatches=[],
                detected_delimiter=detected_delim,
                summary="No column names identified in header row",
            )

        # 4. Compare with Expected Schema Fields
        header_normalized = {c.lower(): c for c in header_cols_clean}
        expected_fields = schema_version.fields

        missing_required = []
        missing_optional = []
        missing_all = []

        for field in expected_fields:
            fname_lower = field.field_name.strip().lower()
            if fname_lower not in header_normalized:
                missing_all.append(field.field_name)
                if field.is_required:
                    missing_required.append(field.field_name)
                else:
                    missing_optional.append(field.field_name)

        expected_normalized = {f.field_name.strip().lower() for f in expected_fields}
        unexpected_fields = [
            header_normalized[c_lower]
            for c_lower in header_normalized
            if c_lower not in expected_normalized
        ]

        # 5. Classify Severity
        is_breaking = False
        summary_parts = []

        if delimiter_mismatch:
            is_breaking = True
            summary_parts.append(f"Delimiter mismatch (expected '{expected_delimiter}', detected '{detected_delim}')")

        if missing_required:
            is_breaking = True
            summary_parts.append(f"Missing required fields: {', '.join(missing_required)}")

        if missing_optional:
            summary_parts.append(f"Missing optional fields: {', '.join(missing_optional)}")

        if unexpected_fields:
            summary_parts.append(f"Unexpected extra fields: {', '.join(unexpected_fields)}")

        if is_breaking:
            drift_severity = DriftSeverityEnum.BREAKING
            summary = "BREAKING DRIFT: " + "; ".join(summary_parts)
        elif missing_optional or unexpected_fields:
            drift_severity = DriftSeverityEnum.NON_BREAKING
            summary = "NON-BREAKING DRIFT: " + "; ".join(summary_parts)
        else:
            drift_severity = DriftSeverityEnum.NONE
            summary = "No schema drift detected; structure matches published contract"

        return DriftDetectionResult(
            drift_severity=drift_severity,
            missing_fields=missing_all,
            missing_required=missing_required,
            missing_optional=missing_optional,
            unexpected_fields=unexpected_fields,
            type_mismatches=[],
            detected_delimiter=detected_delim,
            summary=summary,
        )
