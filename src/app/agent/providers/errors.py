class ModelProviderError(Exception):
    pass


class ModelProviderTimeoutError(ModelProviderError):
    pass


class ModelProviderResponseError(ModelProviderError):
    pass
