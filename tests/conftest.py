import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Permite importar main sin usar credenciales reales ni crear archivos secretos.
os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-with-enough-length")
