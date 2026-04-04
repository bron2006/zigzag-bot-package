import pandas as pd
import pandas_ta as ta
import numpy as np

# 1. Створюємо "фейкові" дані (300 свічок), щоб перевірити математику
data = {
    "Open": np.random.uniform(66000, 67000, 300),
    "High": np.random.uniform(67001, 68000, 300),
    "Low": np.random.uniform(65000, 65999, 300),
    "Close": np.random.uniform(66000, 67000, 300),
    "Volume": np.random.uniform(10, 100, 300)
}
df = pd.DataFrame(data)

print("--- Перевірка розрахунку індикаторів ---")

try:
    # 2. Рахуємо саме твій набір
    df.ta.rsi(length=14, append=True)
    df.ta.adx(length=14, append=True)
    df.ta.atr(length=14, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.ema(length=200, append=True)

    # 3. Витягуємо назви колонок, які згенерувала бібліотека
    print(f"Доступні колонки: {df.columns.tolist()[-10:]}")

    # 4. Формуємо фінальний рядок (Features)
    # УВАГА: Назви мають збігатися з тими, що видав pandas_ta
    latest = df.tail(1)
    features = {
        "ATR": latest["ATRr_14"].values[0],
        "ADX": latest["ADX_14"].values[0],
        "RSI": latest["RSI_14"].values[0],
        "EMA50": latest["EMA_50"].values[0],
        "EMA200": latest["EMA_200"].values[0]
    }

    print("\n--- РЕЗУЛЬТАТ ДЛЯ ШІ ---")
    for name, value in features.items():
        print(f"{name}: {value:.4f}")
    
    print("\n✅ Математика працює. Бібліотека pandas_ta готова.")

except Exception as e:
    print(f"\n❌ Помилка: {e}")
    print("Можливо, треба встановити бібліотеку: pip install pandas-ta")