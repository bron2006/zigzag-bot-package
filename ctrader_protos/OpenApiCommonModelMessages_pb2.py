# OpenApiCommonModelMessages_pb2.py (Спрощена версія)
from google.protobuf.internal import enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor.FileDescriptor(name='OpenApiCommonModelMessages.proto', package='com.xtrader.protocol.openapi.v2', syntax='proto3', serialized_pb=b'\n OpenApiCommonModelMessages.proto\x12\x1f\x63om.xtrader.protocol.openapi.v2\"v\n\rProtoOATrendbar\x12\x0e\n\x06volume\x18\x03 \x01(\x03\x12\x0c\n\x04open\x18\x04 \x01(\x04\x12\r\n\x05\x63lose\x18\x05 \x01(\x04\x12\x0c\n\x04high\x18\x06 \x01(\x04\x12\x0b\n\x03low\x18\x07 \x01(\x04\x12\x1d\n\x15utcTimestampInMinutes\x18\x08 \x01(\r*\x8f\x01\n\x16ProtoOATrendbarPeriod\x12\x06\n\x02M1\x10\x01\x12\x07\n\x03M15\x10\x07\x12\x06\n\x02H1\x10\t\x12\x07\n\x03H4\x10\n\x12\x06\n\x02D1\x10\x0c\x12\x08\n\x04MIN1\x10\x01\x12\t\n\x05MIN15\x10\x07\x12\x08\n\x04HOUR\x10\t\x12\n\n\x06HOUR4\x10\n\x12\x07\n\x03\x44\x41Y\x10\x0c\x1a\x02\x10\x01b\x06proto3')

_PROTOOATRENDBARPERIOD = _descriptor.EnumDescriptor(name='ProtoOATrendbarPeriod', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbarPeriod', values=[
    _descriptor.EnumValueDescriptor(name='M1', index=0, number=1, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='M15', index=1, number=7, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='H1', index=2, number=9, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='H4', index=3, number=10, type=None, create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(name='D1', index=4, number=12, type=None, create_key=_descriptor._internal_create_key),
])
ProtoOATrendbarPeriod = enum_type_wrapper.EnumTypeWrapper(_PROTOOATRENDBARPERIOD)
M1 = 1; M15 = 7; H1 = 9; H4 = 10; D1 = 12

_PROTOOATRENDBAR = _descriptor.Descriptor(name='ProtoOATrendbar', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar', fields=[
    _descriptor.FieldDescriptor(name='volume', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.volume', index=0, number=3, type=3, cpp_type=2, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='open', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.open', index=1, number=4, type=4, cpp_type=4, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='close', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.close', index=2, number=5, type=4, cpp_type=4, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='high', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.high', index=3, number=6, type=4, cpp_type=4, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='low', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.low', index=4, number=7, type=4, cpp_type=4, label=1, create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(name='utcTimestampInMinutes', full_name='com.xtrader.protocol.openapi.v2.ProtoOATrendbar.utcTimestampInMinutes', index=5, number=8, type=13, cpp_type=3, label=1, create_key=_descriptor._internal_create_key),
])
ProtoOATrendbar = _reflection.GeneratedProtocolMessageType('ProtoOATrendbar', (_message.Message,), {'DESCRIPTOR': _PROTOOATRENDBAR, '__module__': 'OpenApiCommonModelMessages_pb2'})
_sym_db.RegisterMessage(ProtoOATrendbar)