import json
import math
import re
from datetime import datetime, timezone

from flask import request


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid(message):
    return ApiError(400, "invalid_input", message)


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
                       r"(?:\.[0-9]{1,6})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})")


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise invalid(f"{field} must be an ID of 1 to 128 ASCII characters")
    return value


def choice(value, field, choices):
    if value not in choices:
        raise invalid(f"{field} must be one of: {', '.join(choices)}")
    return value


def number(value, field, lower=None, upper=None):
    try:
        result = float(value) if type(value) in (int, float) else math.nan
    except OverflowError:
        result = math.nan
    if not math.isfinite(result) or (lower is not None and result < lower) or (
        upper is not None and result > upper
    ):
        raise invalid(f"{field} must be a finite number in range")
    return result or 0.0


def integer(value, field, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise invalid(f"{field} must be an integer from {lower} to {upper}")
    return value


def nonempty_text(value, field, limit=1024):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise invalid(f"{field} must be non-empty text up to {limit} characters")
    return value.strip()


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def timestamp(value, field):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise invalid(f"{field} must be an RFC 3339 timestamp with a timezone")
    if value[-1] not in 'Zz' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise invalid(f"{field} has an invalid UTC offset")
    try:
        return utc_text(datetime.fromisoformat(value.upper().replace("Z", "+00:00")))
    except (ValueError, OverflowError):
        raise invalid(f"{field} is outside the supported timestamp range") from None


def time_range(start, end, start_field="from", end_field="to"):
    start = timestamp(start, start_field) if start is not None else None
    end = timestamp(end, end_field) if end is not None else None
    if start and end and start >= end:
        raise invalid(f"{start_field} must precede {end_field}")
    return start, end


def object_fields(value, field, required=(), optional=()):
    if not isinstance(value, dict):
        raise invalid(f"{field} must be a JSON object")
    missing = sorted(set(required) - value.keys())
    unknown = sorted(value.keys() - set(required) - set(optional))
    if missing:
        raise invalid(f"{field} is missing: {', '.join(missing)}")
    if unknown:
        raise invalid(f"{field} has unsupported fields: {', '.join(unknown)}")
    return value


def unique_object(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("Duplicate JSON key")
    return result


def json_body():
    if request.mimetype != "application/json":
        raise ApiError(415, "unsupported_media_type", "Use application/json")
    try:
        body = request.get_data().decode("utf-8")
        result = json.loads(body, object_pairs_hook=unique_object)
        # Reject non-finite values and unpaired Unicode surrogates even in evidence.
        canonical_json(result).encode("utf-8")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise ApiError(400, "invalid_json", "Send a valid UTF-8 JSON body") from None


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
