from backend.core.config import settings
from backend.adapters.storage.base import StorageAdapter
from backend.adapters.storage.local_adapter import LocalFilesystemAdapter

def get_storage_adapter() -> StorageAdapter:
    if settings.STORAGE_ADAPTER == "local":
        return LocalFilesystemAdapter()
    else:
        raise NotImplementedError(f"Storage adapter '{settings.STORAGE_ADAPTER}' not yet implemented. See UNKNOWN_AND_INTEGRATION_REGISTER.md")