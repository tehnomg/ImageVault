class ServiceError(Exception):
    """Бизнес-ошибка с HTTP-кодом. Единая для API/MCP/UI."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

HTTP_CODES = {"bad_request": 400, "forbidden": 403, "not_found": 404,
              "offline": 409, "conflict": 409}