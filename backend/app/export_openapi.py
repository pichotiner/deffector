"""Выгрузка схемы API в backend/openapi.json (открывается без интернета).

    cd backend && python -m app.export_openapi
"""

import json

from .config import BACKEND
from .main import app

if __name__ == "__main__":
    path = BACKEND / "openapi.json"
    path.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Схема записана: {path}")
