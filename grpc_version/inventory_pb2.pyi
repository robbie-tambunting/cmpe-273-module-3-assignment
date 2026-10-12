from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ReserveRequest(_message.Message):
    __slots__ = ("item_id", "quantity", "idempotency_key")
    ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    item_id: str
    quantity: int
    idempotency_key: str
    def __init__(self, item_id: _Optional[str] = ..., quantity: _Optional[int] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class ReserveResponse(_message.Message):
    __slots__ = ("reservation_id", "item_id", "quantity")
    RESERVATION_ID_FIELD_NUMBER: _ClassVar[int]
    ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    reservation_id: str
    item_id: str
    quantity: int
    def __init__(self, reservation_id: _Optional[str] = ..., item_id: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...
