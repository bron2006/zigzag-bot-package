# -*- coding: utf-8 -*-
# Manually created compatible version for ZigZag Bot
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x15OpenApiMessages.proto\x12\x10OpenApi.Messages\"G\n\x0cProtoMessage\x12\x13\n\x0bpayloadType\x18\x01 \x01(\r\x12\x0f\n\x07payload\x18\x02 \x01(\x0c\x12\x11\n\tclientMsgId\x18\x03 \x01(\tB\x02H\x01b\x06proto3')

_PROTOMESSAGE = DESCRIPTOR.message_types_by_name['ProtoMessage']
ProtoMessage = _reflection.GeneratedProtocolMessageType('ProtoMessage', (_message.Message,), {
  'DESCRIPTOR' : _PROTOMESSAGE,
  '__module__' : 'OpenApiMessages_pb2'
  # @@protoc_insertion_point(class_scope:OpenApi.Messages.ProtoMessage)
  })
_sym_db.RegisterMessage(ProtoMessage)