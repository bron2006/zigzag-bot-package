from typing import Optional, Dict, Any
from telegram.ext import Updater

# Щоб уникнути помилок типізації, поки SpotwareClient ще не визначено,
# можна використовувати 'Any' або текстовий тип.
# from spotware_connect import SpotwareClient

# Спільний стан додатку, доступний для всіх модулів.
client: Optional['SpotwareClient'] = None
symbol_cache: Dict[str, Dict[str, Any]] = {}
updater: Optional[Updater] = None