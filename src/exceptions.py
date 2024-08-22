class ParserFindTagException(Exception):
    """Вызывается, когда парсер не может найти тег."""
    pass


class ResponseError(Exception):
    """Кастомное исключение для ошибки получения ответа."""
    def __init__(self, url, message="Не удалось получить ответ от URL"):
        self.url = url
        self.message = f"{message}: {url}"
        super().__init__(self.message)


class VersionsNotFoundError(Exception):
    """Исключение, если не удается найти список версий Python."""
    def __init__(self, message="Не удалось найти список всех версий Python"):
        self.message = message
        super().__init__(self.message)
