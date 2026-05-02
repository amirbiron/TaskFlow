"""עזרי DB משותפים."""
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status


def validate_object_id(id_str: str) -> ObjectId:
    """ממיר string ל-ObjectId, וזורק 400 אם המזהה לא תקין."""
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מזהה לא תקין",
        )
