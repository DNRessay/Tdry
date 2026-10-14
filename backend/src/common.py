import json
import requests


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def api(fn):
    def wrapper(event, context):
        try:
            try:
                data = json.loads(event.get("body") or "{}")
            except ValueError:
                raise ApiError(400, "invalid JSON body")
            return resp(200, fn(data))
        except ApiError as e:
            return resp(e.status, {"error": str(e)})
        except requests.RequestException as e:
            return resp(502, {"error": f"upstream request failed: {e}"})
        except Exception as e:
            return resp(500, {"error": f"internal error: {e}"})

    return wrapper
