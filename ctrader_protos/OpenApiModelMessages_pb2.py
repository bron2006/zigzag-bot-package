# OpenApiModelMessages_pb2.py (Спрощена версія)
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

_sym_db = _symbol_database.Default()

from ctrader_protos import OpenApiCommonModelMessages_pb2 as OpenApiCommonModelMessages__pb2

DESCRIPTOR = _descriptor.FileDescriptor(name='OpenApiModelMessages.proto', package='com.xtrader.protocol.openapi.v2', syntax='proto3', serialized_pb=b'\n\x1aOpenApiModelMessages.proto\x12\x1f\x63om.xtrader.protocol.openapi.v2\x1a OpenApiCommonModelMessages.proto\"H\n\x1bProtoOAApplicationAuthReq\x12\x10\n\x08\x63lientId\x18\x01 \x01(\t\x12\x17\n\x0f\x63lientSecret\x18\x02 \x01(\t\"G\n\x17ProtoOAAccountAuthReq\x12\x1b\n\x13\x63tidTraderAccountId\x18\x01 \x01(\x03\x12\x13\n\x0b\x61\x63\x63\x65ssToken\x18\x02 \x01(\t\"\xad\x01\n\"ProtoOASubscribeLiveTrendbarReq\x12\x1b\n\x13\x63tidTraderAccountId\x18\x01 \x01(\x03\x12\x10\n\x08symbolId\x18\x02 \x01(\x03\x12R\n\ttimeframe\x18\x03 \x01(\x0e\x32?.com.xtrader.protocol.openapi.v2.ProtoOATrendbarPeriod\"i\n\x14ProtoOATrendbarEvent\x12\x1b\n\x13\x63tidTraderAccountId\x18\x01 \x01(\x03\x12\x10\n\x08symbolId\x18\x02 \x01(\x03\x12\x42\n\x08trendbar\x18\x03 \x03(\x0b\x32\x30.com.xtrader.protocol.openapi.v2.ProtoOATrendbarb\x06proto3')

_PROTOOAAPPLICATIONAUTHREQ = _descriptor.Descriptor(name='ProtoOAApplicationAuthReq', full_name='com.xtrader.protocol.openapi.v2.ProtoOAApplicationAuthReq', fields=[
    _descriptor.FieldDescriptor(name='clientId', full_name='com.xtrader.protocol.openapi.v2.ProtoOAApplicationAuthReq.clientId', index=0, number=1, type=9, cpp_type=9, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='clientSecret', full_name='com.xtrader.protocol.openapi.v2.ProtoOAApplicationAuthReq.clientSecret', index=1, number=2, type=9, cpp_type=9, label=1, create_key=_descriptor._internal_create_key),
])
ProtoOAApplicationAuthReq = _reflection.GeneratedProtocolMessageType('ProtoOAApplicationAuthReq', (_message.Message,), {'DESCRIPTOR': _PROTOOAAPPLICATIONAUTHREQ, '__module__': 'OpenApiModelMessages_pb2'})
_sym_db.RegisterMessage(ProtoOAApplicationAuthReq)

_PROTOOAACCOUNTAUTHREQ = _descriptor.Descriptor(name='ProtoOAAccountAuthReq', full_name='com.xtrader.protocol.openapi.v2.ProtoOAAccountAuthReq', fields=[
    _descriptor.FieldDescriptor(name='ctidTraderAccountId', full_name='com.xtrader.protocol.openapi.v2.ProtoOAAccountAuthReq.ctidTraderAccountId', index=0, number=1, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='accessToken', full_name='com.xtrader.protocol.openapi.v2.ProtoOAAccountAuthReq.accessToken', index=1, number=2, type=9, cpp_type=9, label=1, create_key=_descriptor._internal_create_key),
])
ProtoOAAccountAuthReq = _reflection.GeneratedProtocolMessageType('ProtoOAAccountAuthReq', (_message.Message,), {'DESCRIPTOR': _PROTOOAACCOUNTAUTHREQ, '__module__': 'OpenApiModelMessages_pb2'})
_sym_db.RegisterMessage(ProtoOAAccountAuthReq)

_PROTOOASUBSCRIBELIVETRENDBARREQ = _descriptor.Descriptor(name='ProtoOASubscribeLiveTrendbarReq', full_name='com.xtrader.protocol.openapi.v2.ProtoOASubscribeLiveTrendbarReq', fields=[
    _descriptor.FieldDescriptor(name='ctidTraderAccountId', full_name='com.xtrader.protocol.openapi.v2.ProtoOASubscribeLiveTrendbarReq.ctidTraderAccountId', index=0, number=1, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='symbolId', full_name='com.xtrader.protocol.openapi.v2.ProtoOASubscribeLiveTrendbarReq.symbolId', index=1, number=2, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='timeframe', full_name='com.xtrader.protocol.openapi.v2.ProtoOASubscribeLiveTrendbarReq.timeframe', index=2, number=3, type=14, cpp_type=8, label=1, enum_type=OpenApiCommonModelMessages__pb2._PROTOOATRENDBARPERIOD, create_key=_descriptor._internal_create_key),
])
ProtoOASubscribeLiveTrendbarReq = _reflection.GeneratedProtocolMessageType('ProtoOASubscribeLiveTrendbarReq', (_message.Message,), {'DESCRIPTOR': _PROTOOASUBSCRIBELIVETRENDBARREQ, '__module__': 'OpenApiModelMessages_pb2'})
_sym_db.RegisterMessage(ProtoOASubscribeLiveTrendbarReq)

_PROTOOATRENDBAREVENT = _descriptor.Descriptor(name='ProtoOATrendbarEvent', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbarEvent', fields=[
    _descriptor.FieldDescriptor(name='ctidTraderAccountId', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbarEvent.ctidTraderAccountId', index=0, number=1, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='symbolId', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbarEvent.symbolId', index=1, number=2, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='trendbar', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbarEvent.trendbar', index=2, number=3, type=11, cpp_type=10, label=3, message_type=OpenApiCommonModelMessages__pb2._PROTOOATRENDBAR, create_key=_descriptor._internal_create_key),
])
ProtoOATrendbarEvent = _reflection.GeneratedProtocolMessageType('ProtoOATrendbarEvent', (_message.Message,), {'DESCRIPTOR': _PROTOOATRENDBAREVENT, '__module__': 'OpenApiModelMessages_pb2'})
_sym_db.RegisterMessage(ProtoOATrendbarEvent)