import asyncio
import ssl
import logging
import websockets

from openapi_client.messages import *

class Client:
    def __init__(self, host, port, use_ssl=True):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.websocket = None
        self.listener = None

    def set_listener(self, listener):
        self.listener = listener

    async def connect(self):
        scheme = "wss" if self.use_ssl else "ws"
        uri = f"{scheme}://{self.host}:{self.port}/"
        ssl_context = ssl.create_default_context() if self.use_ssl else None
        self.websocket = await websockets.connect(uri, ssl=ssl_context)
        asyncio.create_task(self._receive())

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()

    async def send(self, message):
        payload_type = message.DESCRIPTOR.GetOptions().Extensions[proto_payload_type]
        proto_message = ProtoMessage(payload=message.SerializeToString(), payloadType=payload_type)
        await self.websocket.send(proto_message.SerializeToString())

    async def _receive(self):
        async for message in self.websocket:
            proto_message = ProtoMessage()
            proto_message.ParseFromString(message)
            if self.listener:
                self.listener(proto_message)