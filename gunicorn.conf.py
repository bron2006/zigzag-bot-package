# gunicorn.conf.py
import os
from multiprocessing import cpu_count

# Gunicorn config variables
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = (cpu_count() * 2) + 1
timeout = 180

def post_worker_init(worker):
    """
    Цей хук викликається один раз для кожного воркер-процесу
    після його створення. Це ідеальне місце для нашої логіки ініціалізації.
    """
    # Ми імпортуємо функцію тут, щоб уникнути циклічних залежностей
    from bot import on_startup
    on_startup(worker)