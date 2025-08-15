# fix_imports.py
import os
import re

# Шлях до папки з protobuf-файлами
PROTO_DIR = "openapi_client/protobuf"

def fix_imports_in_file(file_path):
    """Замінює абсолютні імпорти Protobuf на відносні."""
    with open(file_path, 'r+', encoding='utf-8') as f:
        content = f.read()
        
        # Паттерн для пошуку 'import OpenApi..._pb2'
        pattern = re.compile(r"^(import (OpenApi.*?_pb2))$", re.MULTILINE)
        
        # Заміна на 'from . import ...'
        fixed_content = pattern.sub(r"from . \1", content)

        if fixed_content != content:
            print(f"Виправлено імпорти у файлі: {os.path.basename(file_path)}")
            f.seek(0)
            f.write(fixed_content)
            f.truncate()

def main():
    print(f"Пошук файлів у директорії: {PROTO_DIR}...")
    if not os.path.isdir(PROTO_DIR):
        print(f"Помилка: Директорія {PROTO_DIR} не знайдена.")
        return

    for filename in os.listdir(PROTO_DIR):
        if filename.endswith("_pb2.py"):
            full_path = os.path.join(PROTO_DIR, filename)
            fix_imports_in_file(full_path)
    print("Процес виправлення імпортів завершено.")

if __name__ == "__main__":
    main()