import json
import time
from typing import Callable

from flask import Response
from flask_limiter import RequestLimit


rate_limit_response: Callable[[RequestLimit], Response] = lambda request_limit: Response(
    json.dumps(
        {
            "msg": "Rate limit reached",
            "request_limit": {
                "limit": str(request_limit.limit),
                "reset_at": request_limit.reset_at,
                "reset_after_seconds": request_limit.reset_at - int(time.time()),
            }
        }
    ),
    status=429,
    mimetype='application/json'
)