# ml_models.py
import logging
import joblib
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("ml_models")

# Глобальні змінні для зберігання завантажених моделей
KMEANS_MODEL: KMeans = None
SCALER: StandardScaler = None

def load_models():
    """Завантажує навчені моделі з файлів."""
    global KMEANS_MODEL, SCALER
    try:
        KMEANS_MODEL = joblib.load('market_regime_model.pkl')
        SCALER = joblib.load('scaler.pkl')
        logger.info("✅ ML models ('market_regime_model.pkl', 'scaler.pkl') loaded successfully.")
    except FileNotFoundError:
        logger.error("❌ Could not find model files. Please run data_collector.py and the Jupyter notebook first.")
    except Exception as e:
        logger.exception(f"An error occurred while loading ML models: {e}")