# OpenApiCommonMessages_pb2.py (Спрощена версія)
from google.protobuf.internal import enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor.FileDescriptor(name='OpenApiCommonMessages.proto', package='com.xtrader.protocol.openapi.v2', syntax='proto3', serialized_pb=b'\n\x1bOpenApiCommonMessages.proto\x12\x1f\x63om.xtrader.protocol.openapi.v2\"G\n\x0cProtoMessage\x12\x33\n\x0bpayloadType\x18\x01 \x01(\x0e\x32\x1e.com.xtrader.protocol.openapi.v2.ProtoOAPayloadType\x12\x0f\n\x07payload\x18\x02 \x01(\x0c*\x98\x01\n\x12ProtoOAPayloadType\x12\"\n\x1ePROTO_OA_APPLICATION_AUTH_REQ\x10\xe4\x11\x12\x1f\n\x1bPROTO_OA_ACCOUNT_AUTH_REQ\x10\xe6\x11\x12*\n&PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ\x10\xec\x11\x12\x1f\n\x1bPROTO_OA_TRENDBAR_EVENT\x10\xf2\x11b\x06proto3')

_PROTOOAPAYLOADTYPE = _descriptor.EnumDescriptor(name='ProtoOAPayloadType', full_name='com.xtrader.protocol.openapi.v2.ProtoOAPayloadType', values=[
    _descriptor.EnumValueDescriptor(name='PROTO_OA_APPLICATION_AUTH_REQ', index=0, number=2276, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='PROTO_OA_ACCOUNT_AUTH_REQ', index=1, number=2278, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ', index=2, number=2284, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='PROTO_OA_TRENDBAR_EVENT', index=3, number=2290, type=None, create_key=_descriptor._internal_create_key),
])
ProtoOAPayloadType = enum_type_wrapper.EnumTypeWrapper(_PROTOOAPAYLOADTYPE)
PROTO_OA_APPLICATION_AUTH_REQ = 2276
PROTO_OA_ACCOUNT_AUTH_REQ = 2278
PROTO_OA_SUBSCRIBE_LIVE_TRENDBAR_REQ = 2284
PROTO_OA_TRENDBAR_EVENT = 2290

_PROTOMESSAGE = _descriptor.Descriptor(name='ProtoMessage', full_name='com.xtrader.protocol.openapi.v2.ProtoMessage', fields=[
    _descriptor.FieldDescriptor(name='payloadType', full_name='com.xtrader.protocol.openapi.v2.ProtoMessage.payloadType', index=0, number=1, type=14, cpp_type=8, label=1, enum_type=_PROTOOAPAYLOADTYPE, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='payload', full_name='com.xtrader.protocol.openapi.v2.ProtoMessage.payload', index=1, number=2, type=12, cpp_type=9, label=1, create_key=_descriptor._internal_create_key),
])
ProtoMessage = _reflection.GeneratedProtocolMessageType('ProtoMessage', (_message.Message,), {'DESCRIPTOR': _PROTOMESSAGE, '__module__': 'OpenApiCommonMessages_pb2'})
_sym_db.RegisterMessage(ProtoMessage)