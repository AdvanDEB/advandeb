"""
Shared slowapi Limiter instance.

Defined in its own module so that both ``app.main`` and route modules can
import it without creating a circular import (``main`` imports the route
modules, which would otherwise need to import ``main`` to get the limiter).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


limiter = Limiter(key_func=get_remote_address)
