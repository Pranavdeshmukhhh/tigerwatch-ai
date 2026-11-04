"""Errors contain stable diagnostic codes, never upstream bodies or request URLs."""


class TigerWatchError(RuntimeError):
    pass


class SetupError(TigerWatchError):
    pass


class StoreError(TigerWatchError):
    pass


class LeaseLost(StoreError):
    pass


class ProviderError(TigerWatchError):
    def __init__(self, provider, code, *, retry=True, stop=False, wait=0, unknown=False):
        self.provider = provider
        self.code = code
        self.retry = retry
        self.stop = stop
        self.wait = wait
        self.unknown = unknown
        super().__init__(f"{provider}:{code}")


class UnsafeMedia(TigerWatchError):
    pass


class ExpiredMedia(ProviderError):
    def __init__(self):
        super().__init__("cdn", "expired_or_inaccessible")
