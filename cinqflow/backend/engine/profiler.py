"""
Deterministic Data Profiler Engine — Wave 1 & Wave 3 Slice 1 (CF-V3-E5-05)

Calculates empirical facts from arbitrary input files:
1. Delimited text files (CSV, TSV, pipe-delimited)
2. Complex Healthcare Formats:
   - Nested JSON & NDJSON (Newline Delimited JSON)
   - FHIR JSON Bundles (Patient, Observation, ExplanationOfBenefit, Encounter)
   - Hierarchical XML / CDA structures

Calculates:
- Format auto-detection
- Column / Hierarchical Path discovery
- Record count and path count
- Inferred data types (STRING, INTEGER, DECIMAL, BOOLEAN, DATE, TIMESTAMP)
- Null count & percentage
- Distinct count & percentage
- Min & max values
- Sample values (preserving original values)
- Array statistics (min length, max length, average length)
- Detected date/time patterns

Strictly observational: does NOT alter source data, does NOT use an LLM,
and operates deterministically. Zero PHI in logs.
"""
import io
import csv
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any, Optional, Tuple, Union
from backend.models.schema import SchemaDataTypeEnum


# Common date/time regexes and formats for observation
DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d", "YYYY-MM-DD"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%m/%d/%Y", "MM/DD/YYYY"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%d/%m/%Y", "DD/MM/YYYY"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%m-%d-%Y", "MM-DD-YYYY"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%d-%m-%Y", "DD-MM-YYYY"),
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"), "%Y/%m/%d", "YYYY/MM/DD"),
    (re.compile(r"^\d{8}$"), "%Y%m%d", "YYYYMMDD"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$"), "%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?$"), "%Y-%m-%dT%H:%M:%S", "ISO-8601"),
]

BOOLEAN_STRINGS = {"true", "false", "t", "f", "yes", "no", "y", "n", "1", "0"}
INTEGER_REGEX = re.compile(r"^[-+]?\d+$")
DECIMAL_REGEX = re.compile(r"^[-+]?\d*\.\d+$")


class ColumnProfiler:
    """Accumulates observational facts for a single column or hierarchical path."""

    def __init__(self, name: str, ordinal: int, max_distinct_tracked: int = 10000, is_array: bool = False):
        self.name = name
        self.ordinal = ordinal
        self.max_distinct_tracked = max_distinct_tracked
        self.is_array = is_array
        self.total_count = 0
        self.null_count = 0
        self.distinct_values = set()
        self.sample_values: List[str] = []

        # Numeric values (Decimal)
        self.min_num: Optional[Decimal] = None
        self.max_num: Optional[Decimal] = None
        self.min_num_str: Optional[str] = None
        self.max_num_str: Optional[str] = None
        self.num_count = 0

        # Date values (datetime)
        self.min_dt: Optional[datetime] = None
        self.max_dt: Optional[datetime] = None
        self.min_dt_str: Optional[str] = None
        self.max_dt_str: Optional[str] = None
        self.dt_count = 0

        # Lexicographical fallback
        self.min_str: Optional[str] = None
        self.max_str: Optional[str] = None

        # Array length stats
        self.array_lengths: List[int] = []

        # Type frequency counts
        self.type_counts = {
            SchemaDataTypeEnum.BOOLEAN: 0,
            SchemaDataTypeEnum.INTEGER: 0,
            SchemaDataTypeEnum.DECIMAL: 0,
            SchemaDataTypeEnum.DATE: 0,
            SchemaDataTypeEnum.TIMESTAMP: 0,
            SchemaDataTypeEnum.STRING: 0,
        }
        self.date_patterns_detected: Dict[str, int] = {}

    def observe(self, raw_value: Any) -> None:
        self.total_count += 1

        if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
            self.null_count += 1
            return

        if isinstance(raw_value, list):
            self.is_array = True
            self.array_lengths.append(len(raw_value))
            if len(raw_value) == 0:
                self.null_count += 1
                return
            # Profile child items individually if primitive
            for item in raw_value:
                if not isinstance(item, (dict, list)):
                    self._observe_scalar(str(item))
            return

        if isinstance(raw_value, dict):
            # Object container representation
            val_repr = "{...}"
            if len(self.distinct_values) < self.max_distinct_tracked:
                self.distinct_values.add(val_repr)
            if val_repr not in self.sample_values and len(self.sample_values) < 5:
                self.sample_values.append(val_repr)
            self.type_counts[SchemaDataTypeEnum.STRING] += 1
            return

        self._observe_scalar(str(raw_value).strip())

    def _observe_scalar(self, val: str) -> None:
        # Track distinct values & samples
        if len(self.distinct_values) < self.max_distinct_tracked:
            self.distinct_values.add(val)
        if val not in self.sample_values and len(self.sample_values) < 5:
            self.sample_values.append(val)

        # Lexicographical tracking
        if self.min_str is None or val < self.min_str:
            self.min_str = val
        if self.max_str is None or val > self.max_str:
            self.max_str = val

        # 1. Check Date / Timestamp Patterns
        matched_date = False
        for pat_re, strptime_fmt, label in DATE_PATTERNS:
            if pat_re.match(val):
                try:
                    dt = datetime.strptime(val[:19], strptime_fmt[:len(val[:19])])
                    matched_date = True
                    self.dt_count += 1
                    self.date_patterns_detected[label] = self.date_patterns_detected.get(label, 0) + 1

                    if "HH:MM" in label or "ISO" in label:
                        self.type_counts[SchemaDataTypeEnum.TIMESTAMP] += 1
                    else:
                        self.type_counts[SchemaDataTypeEnum.DATE] += 1

                    if self.min_dt is None or dt < self.min_dt:
                        self.min_dt = dt
                        self.min_dt_str = val
                    if self.max_dt is None or dt > self.max_dt:
                        self.max_dt = dt
                        self.max_dt_str = val
                    break
                except (ValueError, IndexError):
                    pass

        if matched_date:
            return

        # 2. Check Boolean
        if val.lower() in BOOLEAN_STRINGS:
            self.type_counts[SchemaDataTypeEnum.BOOLEAN] += 1
            return

        # 3. Check Integer
        if INTEGER_REGEX.match(val):
            try:
                dec = Decimal(val)
                self.type_counts[SchemaDataTypeEnum.INTEGER] += 1
                self.num_count += 1
                if self.min_num is None or dec < self.min_num:
                    self.min_num = dec
                    self.min_num_str = val
                if self.max_num is None or dec > self.max_num:
                    self.max_num = dec
                    self.max_num_str = val
                return
            except InvalidOperation:
                pass

        # 4. Check Decimal
        if DECIMAL_REGEX.match(val):
            try:
                dec = Decimal(val)
                self.type_counts[SchemaDataTypeEnum.DECIMAL] += 1
                self.num_count += 1
                if self.min_num is None or dec < self.min_num:
                    self.min_num = dec
                    self.min_num_str = val
                if self.max_num is None or dec > self.max_num:
                    self.max_num = dec
                    self.max_num_str = val
                return
            except InvalidOperation:
                pass

        # 5. Fallback: String
        self.type_counts[SchemaDataTypeEnum.STRING] += 1

    def finalize(self) -> Dict[str, Any]:
        non_null_count = self.total_count - self.null_count
        null_pct = round((self.null_count / self.total_count * 100), 2) if self.total_count > 0 else 0.0

        distinct_count = len(self.distinct_values)
        distinct_pct = round((distinct_count / non_null_count * 100), 2) if non_null_count > 0 else 0.0

        # Deterministic inference
        if non_null_count == 0:
            inferred = SchemaDataTypeEnum.STRING
        elif self.type_counts[SchemaDataTypeEnum.BOOLEAN] == non_null_count:
            inferred = SchemaDataTypeEnum.BOOLEAN
        elif self.type_counts[SchemaDataTypeEnum.INTEGER] == non_null_count:
            inferred = SchemaDataTypeEnum.INTEGER
        elif (self.type_counts[SchemaDataTypeEnum.INTEGER] + self.type_counts[SchemaDataTypeEnum.DECIMAL]) == non_null_count:
            inferred = SchemaDataTypeEnum.DECIMAL
        elif self.type_counts[SchemaDataTypeEnum.TIMESTAMP] > 0 and (self.type_counts[SchemaDataTypeEnum.TIMESTAMP] + self.type_counts[SchemaDataTypeEnum.DATE]) == non_null_count:
            inferred = SchemaDataTypeEnum.TIMESTAMP
        elif self.type_counts[SchemaDataTypeEnum.DATE] == non_null_count:
            inferred = SchemaDataTypeEnum.DATE
        else:
            inferred = SchemaDataTypeEnum.STRING

        detected_patterns = [
            {"pattern": pat, "count": cnt}
            for pat, cnt in sorted(self.date_patterns_detected.items(), key=lambda x: -x[1])
        ]

        if inferred in [SchemaDataTypeEnum.INTEGER, SchemaDataTypeEnum.DECIMAL] and self.num_count == non_null_count:
            min_val = self.min_num_str
            max_val = self.max_num_str
        elif inferred in [SchemaDataTypeEnum.DATE, SchemaDataTypeEnum.TIMESTAMP] and self.dt_count == non_null_count:
            min_val = self.min_dt_str
            max_val = self.max_dt_str
        else:
            min_val = self.min_str
            max_val = self.max_str

        array_stats = None
        if self.is_array and self.array_lengths:
            array_stats = {
                "min_length": min(self.array_lengths),
                "max_length": max(self.array_lengths),
                "avg_length": round(sum(self.array_lengths) / len(self.array_lengths), 2),
            }

        return {
            "column_name": self.name,
            "ordinal_position": self.ordinal,
            "inferred_type": inferred,
            "null_count": self.null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_percentage": distinct_pct,
            "min_value": min_val,
            "max_value": max_val,
            "sample_values": self.sample_values,
            "detected_date_patterns": detected_patterns,
            "is_array": self.is_array,
            "array_stats": array_stats,
        }


class DeterministicProfiler:
    """
    Deterministic profiler supporting Delimited (CSV/TSV), JSON, NDJSON, FHIR Bundles, and XML.
    """

    @classmethod
    def detect_format(cls, content_str: str) -> str:
        """Auto-detects format from text content."""
        snippet = content_str.strip()
        if not snippet:
            return "CSV"

        # XML detection
        if snippet.startswith("<?xml") or (snippet.startswith("<") and ">" in snippet[:100] and snippet.endswith(">")):
            return "XML"

        # JSON detection
        if snippet.startswith("{") or snippet.startswith("["):
            try:
                parsed = json.loads(snippet)
                if isinstance(parsed, dict) and parsed.get("resourceType") == "Bundle":
                    return "FHIR"
                if isinstance(parsed, dict) and "resourceType" in parsed:
                    return "FHIR"
                return "JSON"
            except Exception:
                pass

        # NDJSON detection
        first_lines = [line.strip() for line in snippet.split("\n")[:5] if line.strip()]
        if len(first_lines) > 0 and all(line.startswith("{") and line.endswith("}") for line in first_lines):
            try:
                for line in first_lines:
                    json.loads(line)
                return "NDJSON"
            except Exception:
                pass

        return "CSV"

    @classmethod
    def profile_csv(
        cls,
        file_stream: io.TextIOBase,
        delimiter: str = ",",
    ) -> Dict[str, Any]:
        """Profiles delimited text stream."""
        reader = csv.reader(file_stream, delimiter=delimiter)
        try:
            header = next(reader, None)
        except Exception as e:
            raise ValueError(f"Failed to read CSV header: {str(e)}")

        if not header or all(col.strip() == "" for col in header):
            raise ValueError("File is empty or missing a valid header row")

        column_names = [col.strip() for col in header]
        column_profilers = [
            ColumnProfiler(name=name, ordinal=idx + 1)
            for idx, name in enumerate(column_names)
        ]

        row_count = 0
        for row in reader:
            if not row or (len(row) == 1 and row[0].strip() == ""):
                continue

            row_count += 1
            for idx, profiler in enumerate(column_profilers):
                val = row[idx] if idx < len(row) else None
                profiler.observe(val)

        column_stats = [p.finalize() for p in column_profilers]

        return {
            "format": "CSV",
            "is_complex": False,
            "row_count": row_count,
            "column_count": len(column_names),
            "columns": column_stats,
            "summary": {
                "format": "CSV",
                "total_rows": row_count,
                "total_columns": len(column_names),
                "columns_with_nulls": sum(1 for c in column_stats if c["null_count"] > 0),
                "inferred_type_distribution": {
                    t.value: sum(1 for c in column_stats if c["inferred_type"] == t)
                    for t in SchemaDataTypeEnum
                },
            },
        }

    @classmethod
    def _discover_json_paths(cls, obj: Any, prefix: str = "", paths_dict: Optional[Dict[str, List[Any]]] = None) -> Dict[str, List[Any]]:
        """Recursively extracts all hierarchical paths and collects values."""
        if paths_dict is None:
            paths_dict = {}

        if isinstance(obj, dict):
            if not obj and prefix:
                paths_dict.setdefault(prefix, []).append(None)
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, (dict, list)):
                    cls._discover_json_paths(v, prefix=p, paths_dict=paths_dict)
                else:
                    paths_dict.setdefault(p, []).append(v)
        elif isinstance(obj, list):
            array_path = f"{prefix}[*]" if prefix else "[*]"
            # Track the array itself
            paths_dict.setdefault(array_path, []).append(obj)
            for idx, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    cls._discover_json_paths(item, prefix=array_path, paths_dict=paths_dict)
                else:
                    paths_dict.setdefault(array_path, []).append(item)
        else:
            if prefix:
                paths_dict.setdefault(prefix, []).append(obj)

        return paths_dict

    @classmethod
    def profile_json(
        cls,
        content_str: str,
        is_fhir: bool = False,
    ) -> Dict[str, Any]:
        """Profiles single JSON object or array of objects, or FHIR Bundle."""
        try:
            parsed = json.loads(content_str)
        except Exception as e:
            raise ValueError(f"Failed to parse JSON content: {str(e)}")

        records: List[Dict[str, Any]] = []
        root_metadata: Dict[str, Any] = {}

        if is_fhir and isinstance(parsed, dict) and parsed.get("resourceType") == "Bundle":
            root_metadata = {
                "resourceType": parsed.get("resourceType"),
                "type": parsed.get("type"),
                "total": parsed.get("total"),
            }
            # Each entry in FHIR bundle is a record
            entries = parsed.get("entry", [])
            for e in entries:
                if isinstance(e, dict):
                    records.append(e.get("resource") or e)
            if not records:
                records = [parsed]
        elif isinstance(parsed, list):
            records = [item for item in parsed if isinstance(item, dict)]
            if not records and parsed:
                records = [{"value": item} for item in parsed]
        elif isinstance(parsed, dict):
            # Check if dict contains a primary array
            primary_array_key = next((k for k, v in parsed.items() if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict)), None)
            if primary_array_key:
                records = parsed[primary_array_key]
                root_metadata = {k: v for k, v in parsed.items() if k != primary_array_key and not isinstance(v, (dict, list))}
            else:
                records = [parsed]

        total_rows = max(len(records), 1)

        # Map paths to values
        all_paths_dict: Dict[str, List[Any]] = {}
        for rec in records:
            rec_paths = cls._discover_json_paths(rec)
            for path, vals in rec_paths.items():
                all_paths_dict.setdefault(path, []).extend(vals)

        # Profile discovered paths
        column_profilers: List[ColumnProfiler] = []
        hierarchical_paths = []

        for idx, (path, vals) in enumerate(all_paths_dict.items(), start=1):
            is_arr = "[*]" in path
            cp = ColumnProfiler(name=path, ordinal=idx, is_array=is_arr)
            for v in vals:
                cp.observe(v)
            # If records did not have this path, observe None for missing
            missing = total_rows - len(vals)
            for _ in range(max(0, missing)):
                cp.observe(None)

            stat = cp.finalize()
            column_profilers.append(cp)

            depth = path.count(".") + 1
            hierarchical_paths.append({
                "path": path,
                "ordinal_position": idx,
                "depth": depth,
                "is_array": is_arr,
                "inferred_type": stat["inferred_type"].value,
                "null_count": stat["null_count"],
                "null_percentage": stat["null_percentage"],
                "distinct_count": stat["distinct_count"],
                "sample_values": stat["sample_values"],
                "array_stats": stat.get("array_stats"),
            })

        column_stats = [p.finalize() for p in column_profilers]

        detected_format = "FHIR" if is_fhir else "JSON"
        return {
            "format": detected_format,
            "is_complex": True,
            "row_count": total_rows,
            "column_count": len(column_stats),
            "columns": column_stats,
            "hierarchical_paths": hierarchical_paths,
            "summary": {
                "format": detected_format,
                "is_complex": True,
                "root_metadata": root_metadata,
                "total_rows": total_rows,
                "total_columns": len(column_stats),
                "hierarchical_paths_count": len(hierarchical_paths),
                "nested_array_count": sum(1 for p in hierarchical_paths if p["is_array"]),
                "max_hierarchy_depth": max((p["depth"] for p in hierarchical_paths), default=1),
                "columns_with_nulls": sum(1 for c in column_stats if c["null_count"] > 0),
                "inferred_type_distribution": {
                    t.value: sum(1 for c in column_stats if c["inferred_type"] == t)
                    for t in SchemaDataTypeEnum
                },
            },
        }

    @classmethod
    def profile_ndjson(cls, content_str: str) -> Dict[str, Any]:
        """Profiles newline-delimited JSON."""
        lines = [line.strip() for line in content_str.split("\n") if line.strip()]
        if not lines:
            raise ValueError("NDJSON content is empty")

        records = []
        for idx, line in enumerate(lines):
            try:
                records.append(json.loads(line))
            except Exception as e:
                raise ValueError(f"Invalid NDJSON at line {idx + 1}: {str(e)}")

        # Convert to JSON array and profile
        return cls.profile_json(json.dumps(records), is_fhir=False)

    @classmethod
    def profile_xml(cls, content_str: str) -> Dict[str, Any]:
        """Profiles hierarchical XML documents."""
        try:
            root = ET.fromstring(content_str)
        except Exception as e:
            raise ValueError(f"Failed to parse XML content: {str(e)}")

        paths_dict: Dict[str, List[Any]] = {}

        def traverse(node: ET.Element, current_path: str):
            tag = node.tag.split("}")[-1] if "}" in node.tag else node.tag
            path = f"{current_path}.{tag}" if current_path else tag

            # Record attributes
            for attr_name, attr_val in node.attrib.items():
                paths_dict.setdefault(f"{path}@{attr_name}", []).append(attr_val)

            # Record text if terminal
            has_children = len(node) > 0
            if not has_children and node.text and node.text.strip():
                paths_dict.setdefault(path, []).append(node.text.strip())

            # Traverse children
            child_tags: Dict[str, int] = {}
            for child in node:
                c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                child_tags[c_tag] = child_tags.get(c_tag, 0) + 1

            for child in node:
                c_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tags[c_tag] > 1:
                    child_path = f"{path}.{c_tag}[*]"
                else:
                    child_path = path
                traverse(child, child_path)

        traverse(root, "")

        column_profilers = []
        hierarchical_paths = []
        total_rows = 1

        for idx, (path, vals) in enumerate(paths_dict.items(), start=1):
            is_arr = "[*]" in path
            cp = ColumnProfiler(name=path, ordinal=idx, is_array=is_arr)
            for v in vals:
                cp.observe(v)
            stat = cp.finalize()
            column_profilers.append(cp)

            depth = path.count(".") + 1
            hierarchical_paths.append({
                "path": path,
                "ordinal_position": idx,
                "depth": depth,
                "is_array": is_arr,
                "inferred_type": stat["inferred_type"].value,
                "null_count": stat["null_count"],
                "null_percentage": stat["null_percentage"],
                "distinct_count": stat["distinct_count"],
                "sample_values": stat["sample_values"],
            })

        column_stats = [p.finalize() for p in column_profilers]

        return {
            "format": "XML",
            "is_complex": True,
            "row_count": total_rows,
            "column_count": len(column_stats),
            "columns": column_stats,
            "hierarchical_paths": hierarchical_paths,
            "summary": {
                "format": "XML",
                "is_complex": True,
                "root_element": root.tag.split("}")[-1] if "}" in root.tag else root.tag,
                "total_rows": total_rows,
                "total_columns": len(column_stats),
                "hierarchical_paths_count": len(hierarchical_paths),
                "columns_with_nulls": sum(1 for c in column_stats if c["null_count"] > 0),
                "inferred_type_distribution": {
                    t.value: sum(1 for c in column_stats if c["inferred_type"] == t)
                    for t in SchemaDataTypeEnum
                },
            },
        }

    @classmethod
    def profile_auto(cls, content_str: str) -> Dict[str, Any]:
        """Automatically detects format and executes corresponding profiler."""
        fmt = cls.detect_format(content_str)
        if fmt == "FHIR":
            return cls.profile_json(content_str, is_fhir=True)
        elif fmt == "JSON":
            return cls.profile_json(content_str, is_fhir=False)
        elif fmt == "NDJSON":
            return cls.profile_ndjson(content_str)
        elif fmt == "XML":
            return cls.profile_xml(content_str)
        else:
            return cls.profile_csv(io.StringIO(content_str))
