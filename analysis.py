# analysis.py
import logging
import pandas as pd
import pandas_ta as ta # <-- Правильний імпорт
import numpy as np
import time
from typing import Optional, Dict, List

from twisted.internet.defer import Deferred
from twisted.internet import reactor

from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod

from db import add_signal_to_history
from state import app_state

logger = logging.getLogger("analysis")
# ... (решта файлу без змін)