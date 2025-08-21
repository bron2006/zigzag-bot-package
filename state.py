# state.py

from typing import Optional, Any

# Оголошуємо "контейнери" для майбутніх об'єктів.
# Вони будуть ініціалізовані в main.py перед тим, як їх хтось використає.
state: Optional[Any] = None
client: Optional[Any] = None
bot: Optional[Any] = None

class AppState:
    """
    Клас для зберігання всього стану програми.
    Тут будуть дані про акаунти, позиції, налаштування тощо.
    """
    def __init__(self):
        self.message = "Initial state"
        # Наприклад, тут можна зберігати інформацію про торгові рахунки
        self.accounts = {}

    def update_message(self, new_message: str):
        self.message = new_message

    def get_status(self):
        # У майбутньому цей метод буде збирати повний статус з усіх систем
        return f"Current App State: '{self.message}'"