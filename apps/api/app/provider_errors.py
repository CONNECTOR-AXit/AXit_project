"""Provider-neutral typed failures preserved by generation workers."""

class GenerationProviderFailure(ValueError):
    code: str
    retryable: bool

    def __init__(self, code: str, *, retryable: bool, detail: str | None = None) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(detail or code)
