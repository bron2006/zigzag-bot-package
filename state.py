# state.py
class AppState:
    """Клас для зберігання стану програми."""
    def __init__(self):
        self.symbols = []
        # Тут можна додавати інші дані, які потрібно зберігати
        # наприклад, self.account_info = {}

    def set_symbols(self, symbols_list):
        """Зберігає відсортований список імен символів."""
        if symbols_list:
            self.symbols = sorted([s.symbolName for s in symbols_list])

    def get_symbols(self):
        """Повертає збережений список символів."""
        return self.symbols