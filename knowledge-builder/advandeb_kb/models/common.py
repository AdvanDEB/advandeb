"""
Shared types used across all knowledge-builder models.
"""
import re
from typing import Any, Annotated, Union
from pydantic import BeforeValidator, PlainSerializer, PlainValidator
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


# ArangoDB document keys: 1–254 characters from this set (no "/", which
# separates collection and key in a full _id such as "facts/<key>").
_ARANGO_KEY_RE = re.compile(r"[A-Za-z0-9_\-:.@()+,=;$!*'%]{1,254}")
# Only the lowercase spelling, which is what str(ObjectId) gives back: an
# uppercase hex key would come back lowercased and no longer match its row.
_OBJECT_ID_HEX_RE = re.compile(r"[0-9a-f]{24}")


def _validate_object_id_or_key(v: Any) -> Union[ObjectId, str]:
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str):
        if _OBJECT_ID_HEX_RE.fullmatch(v):
            return ObjectId(v)
        if _ARANGO_KEY_RE.fullmatch(v):
            return v
    raise ValueError(f"Not an ObjectId or ArangoDB document key: {v!r}")


# The key of a knowledge entity (document, fact, stylized fact, relation),
# or a reference to one. Most were minted as ObjectIds — Mongo-era records,
# and everything created through the models — and stay ObjectId, exactly as
# with PyObjectId. Others are keyed by an external id or a composite and stay
# the string they are: reproduction documents by OpenAlex work id
# ("W2810246872") or a "doi_"/"rec_" hash, sf_support edges by
# "<fact key>_<sf key>". str() gives the ArangoDB _key in both cases.
#
# A plain validator, not a Union for pydantic to resolve: a smart-mode union
# would keep a hex string as str rather than turn it into the ObjectId that
# the same id gets everywhere else.
ObjectIdOrKey = Annotated[
    Union[ObjectId, str],
    PlainValidator(_validate_object_id_or_key),
    PlainSerializer(lambda x: str(x), return_type=str, when_used="json"),
]
