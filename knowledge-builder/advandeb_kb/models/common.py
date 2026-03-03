"""
Shared types used across all knowledge-builder models.
"""
from typing import Any, Annotated
from pydantic import BeforeValidator, PlainSerializer
from bson import ObjectId


def _validate_object_id(v: Any) -> ObjectId:
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str) and ObjectId.is_valid(v):
        return ObjectId(v)
    raise ValueError(f"Invalid ObjectId: {v!r}")


# ObjectId is preserved as-is in model_dump() so Motor/pymongo receive the
# correct type for MongoDB operations. It is serialized to a plain string only
# when producing JSON output (model_dump(mode='json') or model.model_json()).
PyObjectId = Annotated[
    ObjectId,
    BeforeValidator(_validate_object_id),
    PlainSerializer(lambda x: str(x), return_type=str, when_used="json"),
]
