from slowapi import Limiter
from slowapi.util import get_remote_address

# Limiter compartido. Vive en su propio modulo para que tanto main.py
# (registro del handler) como las rutas (decoradores) lo importen sin
# crear dependencias circulares.
limiter = Limiter(key_func=get_remote_address)
