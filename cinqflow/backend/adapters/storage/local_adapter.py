from pathlib import Path
from backend.adapters.storage.base import StorageAdapter
from backend.core.config import settings

class LocalFilesystemAdapter(StorageAdapter):
    """Local filesystem storage for DEV. All data stored under LOCAL_STORAGE_ROOT."""
    
    def __init__(self):
        Path(settings.LOCAL_STORAGE_ROOT).mkdir(parents=True, exist_ok=True)
        Path(settings.LANDING_ZONE_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.BRONZE_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.SILVER_RAW_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.QUARANTINE_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.SAMPLE_PATH).mkdir(parents=True, exist_ok=True)
    
    def write_file(self, destination_path: str, content: bytes) -> str:
        path = Path(destination_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)
    
    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()
    
    def file_exists(self, path: str) -> bool:
        return Path(path).exists()
    
    def list_files(self, directory: str) -> list[str]:
        p = Path(directory)
        if not p.exists():
            return []
        return [str(f) for f in p.iterdir() if f.is_file()]
    
    def get_adapter_name(self) -> str:
        return "local_filesystem"