"""
Structural Transform Engine — Wave 3 Slice 1 (CF-V3-E6-05)

Provides deterministic structural transforms for complex healthcare formats:
- PATH_EXTRACT: Extracts specific nested values via JSONPath or dot-notation.
- EXPLODE: Unnests arrays into multiple denormalized rows (with inner/outer join modes).
- FLATTEN: Flattens nested object hierarchies into dot/underscore prefixed fields.
- ARRAY_MAP: Maps, filters, and formats array elements into scalar or list representations.
- UNNEST: Extracts nested composite objects into top-level canonical fields.

Supports JSON, FHIR JSON Bundles, NDJSON, and nested dictionaries.
Zero-PHI in logs or compiled specifications.
"""
import re
import copy
from typing import Any, Dict, List, Optional, Union
from backend.models.mapping import TransformTypeEnum


# Regex for JSONPath filter expression: e.g. [?(@.system == 'phone')] or [?(@.code=='MR')]
FILTER_REGEX = re.compile(r"^\[\?\(@\.([\w\.\-]+)\s*(==|!=)\s*['\"]?([^'\"]*?)['\"]?\)\]$")
ARRAY_INDEX_REGEX = re.compile(r"^(\w+)?\[(\d+)\]$")
ARRAY_WILDCARD_REGEX = re.compile(r"^(\w+)?\[\*\]$")


def _tokenize_path(path: str) -> List[str]:
    """
    Tokenizes dot and bracket notation paths while preserving filter expressions.
    E.g. "entry[*].resource.telecom[?(@.system=='phone')].value" ->
    ['entry[*]', 'resource', 'telecom[?(@.system==\'phone\')]', 'value']
    """
    if not path or not path.strip():
        return []
    
    clean_path = path.strip()
    if clean_path.startswith("$."):
        clean_path = clean_path[2:]
    elif clean_path.startswith("$"):
        clean_path = clean_path[1:]
    
    tokens = []
    current = []
    in_bracket = False
    in_quote = False
    quote_char = None
    
    for ch in clean_path:
        if ch in ("'", '"') and in_bracket:
            if not in_quote:
                in_quote = True
                quote_char = ch
            elif quote_char == ch:
                in_quote = False
                quote_char = None
            current.append(ch)
        elif ch == '[' and not in_quote:
            in_bracket = True
            current.append(ch)
        elif ch == ']' and not in_quote:
            in_bracket = False
            current.append(ch)
        elif ch == '.' and not in_bracket:
            part = "".join(current).strip()
            if part:
                tokens.append(part)
            current = []
        else:
            current.append(ch)
            
    last_part = "".join(current).strip()
    if last_part:
        tokens.append(last_part)
        
    return tokens


def extract_path(data: Any, path: str, default: Any = None) -> Any:
    """
    Robust JSONPath / dot-path evaluator.
    Supports:
    - Dot notation: 'patient.address.city'
    - Array index: 'name[0].family' or 'telecom[1]'
    - Array wildcard: 'identifier[*].value' (returns list of values)
    - Filter expression: 'telecom[?(@.system == 'email')].value'
    """
    if data is None or not path:
        return default

    tokens = _tokenize_path(path)
    current: Any = data

    for idx, token in enumerate(tokens):
        if current is None:
            return default

        # 1. Check for filter: e.g. telecom[?(@.system=='phone')]
        bracket_start = token.find("[?(")
        if bracket_start != -1 and token.endswith(")]"):
            field_name = token[:bracket_start]
            filter_expr = token[bracket_start:]
            if field_name:
                if isinstance(current, dict):
                    current = current.get(field_name)
                else:
                    return default
            
            if not isinstance(current, list):
                return default
                
            m = FILTER_REGEX.match(filter_expr)
            if m:
                filter_key, op, filter_val = m.groups()
                matched = []
                for item in current:
                    if isinstance(item, dict):
                        item_val = extract_path(item, filter_key, None)
                        if op == "==" and str(item_val) == filter_val:
                            matched.append(item)
                        elif op == "!=" and str(item_val) != filter_val:
                            matched.append(item)
                # If subsequent tokens exist, apply to matched items
                remaining = ".".join(tokens[idx + 1:])
                if remaining:
                    results = []
                    for it in matched:
                        res = extract_path(it, remaining, None)
                        if res is not None:
                            results.append(res)
                    return results if len(results) > 1 else (results[0] if results else default)
                return matched if len(matched) > 1 else (matched[0] if matched else default)
            return default

        # 2. Check for array index: name[0] or [0]
        m_idx = ARRAY_INDEX_REGEX.match(token)
        if m_idx:
            field_name, array_idx_str = m_idx.groups()
            array_idx = int(array_idx_str)
            if field_name:
                if isinstance(current, dict):
                    current = current.get(field_name)
                else:
                    return default
            if isinstance(current, (list, tuple)):
                if 0 <= array_idx < len(current):
                    current = current[array_idx]
                else:
                    return default
            else:
                return default
            continue

        # 3. Check for array wildcard: items[*] or [*]
        m_wild = ARRAY_WILDCARD_REGEX.match(token)
        if m_wild:
            field_name = m_wild.group(1)
            if field_name:
                if isinstance(current, dict):
                    current = current.get(field_name)
                else:
                    return default
            if not isinstance(current, (list, tuple)):
                return default
            
            remaining = ".".join(tokens[idx + 1:])
            if remaining:
                results = []
                for it in current:
                    val = extract_path(it, remaining, None)
                    if val is not None:
                        if isinstance(val, list):
                            results.extend(val)
                        else:
                            results.append(val)
                return results if results else default
            return list(current)

        # 4. Standard dictionary field lookup
        if isinstance(current, dict):
            # Check exact match first
            if token in current:
                current = current[token]
            else:
                # Case-insensitive fallback
                lower_map = {k.lower(): k for k in current.keys()}
                if token.lower() in lower_map:
                    current = current[lower_map[token.lower()]]
                else:
                    return default
        else:
            return default

    return current if current is not None else default


def apply_explode(
    record: Dict[str, Any],
    array_path: str,
    target_field: Optional[str] = None,
    outer_join: bool = True,
) -> List[Dict[str, Any]]:
    """
    Explodes an array inside a record into multiple child records.
    Outer join (default): if array is empty or None, produces 1 row with None.
    Inner join: if array is empty or None, produces 0 rows.
    """
    if not record or not isinstance(record, dict):
        return []

    target_col = target_field or array_path.split(".")[-1].replace("[*]", "")
    items = extract_path(record, array_path, None)

    if items is None or not isinstance(items, list) or len(items) == 0:
        if outer_join:
            row_copy = copy.deepcopy(record)
            row_copy[target_col] = None
            row_copy["_explode_index"] = 0
            return [row_copy]
        return []

    exploded_rows = []
    for idx, item in enumerate(items):
        row_copy = copy.deepcopy(record)
        row_copy[target_col] = item
        row_copy["_explode_index"] = idx
        exploded_rows.append(row_copy)

    return exploded_rows


def apply_flatten(
    obj: Dict[str, Any],
    prefix: str = "",
    separator: str = "_",
    max_depth: int = 5,
    current_depth: int = 1,
) -> Dict[str, Any]:
    """
    Recursively flattens nested dicts into a single-level dictionary.
    E.g. {"name": {"family": "Smith", "given": ["John"]}} -> {"name_family": "Smith", "name_given": ["John"]}
    """
    if not isinstance(obj, dict):
        return {prefix: obj} if prefix else {}

    flattened: Dict[str, Any] = {}

    for key, value in obj.items():
        field_name = f"{prefix}{separator}{key}" if prefix else str(key)
        if isinstance(value, dict) and current_depth < max_depth:
            sub = apply_flatten(
                value,
                prefix=field_name,
                separator=separator,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
            flattened.update(sub)
        else:
            flattened[field_name] = value

    return flattened


def apply_path_extract(
    obj: Dict[str, Any],
    path: str,
    default: Any = None,
) -> Any:
    """Extracts a value at path."""
    return extract_path(obj, path, default)


def apply_array_map(
    obj: Dict[str, Any],
    array_path: str,
    element_path: Optional[str] = None,
    delimiter: Optional[str] = ", ",
    filter_key: Optional[str] = None,
    filter_val: Optional[str] = None,
) -> Any:
    """
    Extracts, filters, and formats array elements.
    If delimiter is provided, joins extracted elements as a string.
    Otherwise returns a list of extracted elements.
    """
    items = extract_path(obj, array_path, None)
    if items is None or not isinstance(items, list):
        return None

    mapped_elements = []
    for item in items:
        if filter_key is not None:
            actual_val = extract_path(item, filter_key, None) if isinstance(item, dict) else None
            if str(actual_val) != str(filter_val):
                continue

        if element_path and isinstance(item, (dict, list)):
            val = extract_path(item, element_path, None)
            if val is not None:
                mapped_elements.append(val)
        else:
            if item is not None:
                mapped_elements.append(item)

    if delimiter is not None:
        return delimiter.join(str(x) for x in mapped_elements)
    return mapped_elements


def apply_unnest(
    obj: Dict[str, Any],
    path: str,
    properties: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Extracts nested composite object and returns its attributes.
    """
    target = extract_path(obj, path, None)
    if not isinstance(target, dict):
        return {}

    if properties:
        return {p: target.get(p) for p in properties if p in target}
    return dict(target)


class StructuralTransformEngine:
    """
    Dispatcher and execution engine for all 12 mapping transform types
    (7 baseline transforms + 5 Wave 3 structural transforms).
    """

    @classmethod
    def evaluate(
        cls,
        transform_type: Union[TransformTypeEnum, str],
        transform_params: Dict[str, Any],
        source_fields: List[str],
        row_or_obj: Dict[str, Any],
    ) -> Any:
        ttype = TransformTypeEnum(transform_type) if isinstance(transform_type, str) else transform_type
        params = transform_params or {}

        # 1. EXPLODE (returns exploded item for row if row has target, or extracts array)
        if ttype == TransformTypeEnum.EXPLODE:
            array_path = params.get("array_path") or (source_fields[0] if source_fields else "")
            target_field = params.get("target_field")
            if target_field and target_field in row_or_obj:
                return row_or_obj[target_field]
            items = extract_path(row_or_obj, array_path, None)
            return items[0] if isinstance(items, list) and items else items

        # 2. FLATTEN
        if ttype == TransformTypeEnum.FLATTEN:
            prefix = params.get("prefix", "")
            separator = params.get("separator", "_")
            max_depth = int(params.get("max_depth", 5))
            src = source_fields[0] if source_fields else None
            sub = extract_path(row_or_obj, src) if src else row_or_obj
            if isinstance(sub, dict):
                return apply_flatten(sub, prefix=prefix, separator=separator, max_depth=max_depth)
            return sub

        # 3. PATH_EXTRACT
        if ttype == TransformTypeEnum.PATH_EXTRACT:
            path = params.get("path") or (source_fields[0] if source_fields else "")
            default = params.get("default")
            return extract_path(row_or_obj, path, default=default)

        # 4. ARRAY_MAP
        if ttype == TransformTypeEnum.ARRAY_MAP:
            array_path = params.get("array_path") or (source_fields[0] if source_fields else "")
            element_path = params.get("element_path")
            delimiter = params.get("delimiter", ", ")
            filter_key = params.get("filter_key")
            filter_val = params.get("filter_val")
            return apply_array_map(
                row_or_obj,
                array_path=array_path,
                element_path=element_path,
                delimiter=delimiter,
                filter_key=filter_key,
                filter_val=filter_val,
            )

        # 5. UNNEST
        if ttype == TransformTypeEnum.UNNEST:
            path = params.get("path") or (source_fields[0] if source_fields else "")
            properties = params.get("properties")
            return apply_unnest(row_or_obj, path=path, properties=properties)

        # Baseline Transforms Fallback
        src_name = source_fields[0] if source_fields else None
        raw_val = extract_path(row_or_obj, src_name) if src_name else None

        if ttype == TransformTypeEnum.DIRECT:
            return raw_val

        if ttype == TransformTypeEnum.CONSTANT:
            return params.get("value")

        if ttype == TransformTypeEnum.VALUE_MAP:
            dictionary = params.get("dictionary", {})
            on_unmapped = params.get("on_unmapped", "DEFAULT")
            fallback = params.get("default")
            if raw_val in dictionary:
                return dictionary[raw_val]
            if on_unmapped == "NULL":
                return None
            return fallback

        if ttype == TransformTypeEnum.CONCAT:
            delimiter = params.get("delimiter", " ")
            parts = [str(extract_path(row_or_obj, s, "") or "") for s in source_fields]
            return delimiter.join(parts)

        if ttype == TransformTypeEnum.COALESCE:
            for s in source_fields:
                v = extract_path(row_or_obj, s, None)
                if v is not None and v != "":
                    return v
            return None

        if ttype == TransformTypeEnum.STRING_CLEAN:
            if raw_val is not None:
                val = str(raw_val)
                if params.get("trim", True):
                    val = val.strip()
                casing = params.get("casing", "NONE")
                if casing == "UPPER":
                    val = val.upper()
                elif casing == "LOWER":
                    val = val.lower()
                return val
            return None

        return raw_val
