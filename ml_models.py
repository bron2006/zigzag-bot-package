# ml_models.py
import logging
import joblib
import lightgbm as lgb # Додаємо імпорт
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("ml_models")

# Глобальні змінні для зберігання нових моделей
LGBM_MODEL: lgb.LGBMClassifier = None
SCALER: StandardScaler = None

def load_models():
    """Завантажує навчені моделі з файлів."""
    global LGBM_MODEL, SCALER
    try:
        LGBM_MODEL = joblib.load('lgbm_model.pkl')
        SCALER = joblib.load('lgbm_scaler.pkl')
        logger.info("✅ ML models ('lgbm_model.pkl', 'lgbm_scaler.pkl') loaded successfully.")
    except FileNotFoundError:
        logger.error("❌ Could not find model files. Please run the Jupyter notebook first.")
    except Exception as e:
        logger.exception(f"An error occurred while loading ML models: {e}")