from datetime import UTC, datetime

import pytest

from keelmodel.runtime.errors import ValidationError
from keelmodel.runtime.serialization import deserialize_value
from keelmodel.schema import FieldDefinition as F


def test_boolean_rejects_coercible_values():
    f = F("flag", "boolean")
    assert deserialize_value(f, True) is True
    for bad in ("false", "true", 0, 1, "0"):
        with pytest.raises(ValidationError):
            deserialize_value(f, bad)


def test_integer_rejects_floats_and_non_digit_strings():
    f = F("count", "integer")
    assert deserialize_value(f, 5) == 5
    assert deserialize_value(f, "42") == 42
    for bad in (3.9, "3.9", "abc", True):
        with pytest.raises(ValidationError):
            deserialize_value(f, bad)


def test_datetime_requires_timezone():
    f = F("at", "datetime")
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    assert deserialize_value(f, aware) == aware
    assert deserialize_value(f, "2026-01-01T00:00:00+00:00") == aware
    with pytest.raises(ValidationError, match="timezone"):
        deserialize_value(f, "2026-01-01T00:00:00")
    with pytest.raises(ValidationError, match="timezone"):
        deserialize_value(f, datetime(2026, 1, 1))


def test_url_requires_http_scheme_and_host():
    f = F("link", "url")
    assert deserialize_value(f, "https://a.example/x") == "https://a.example/x"
    for bad in ("ftp://a.example", "not-a-url", "https://", "https:path"):
        with pytest.raises(ValidationError):
            deserialize_value(f, bad)


def test_enum_rejects_out_of_values():
    f = F("status", "enum", values=("draft", "paid"))
    assert deserialize_value(f, "draft") == "draft"
    with pytest.raises(ValidationError):
        deserialize_value(f, "archived")


def test_text_rejects_non_string():
    f = F("name", "text")
    with pytest.raises(ValidationError):
        deserialize_value(f, 123)
