from __future__ import annotations

import json
from typing import Any, Dict

import orjson


def loads_json(text: str) -> Dict[str, Any]:
    try:
        return orjson.loads(text)
    except Exception:
        return json.loads(text)
