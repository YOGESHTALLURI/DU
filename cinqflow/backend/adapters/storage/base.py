from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

class StorageAdapter(ABC):
    """Interface for file storage.
    DEV: LocalFilesystemAdapter
    PROD: AzureBlobAdapter or S3Adapter (not yet implemented)
    """
    
    @abstractmethod
    def write_file(self, destination_path: str, content: bytes) -> str:
        """Write bytes to storage. Returns the storage path."""
        ...
    
    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read bytes from storage."""
        ...
    
    @abstractmethod
    def file_exists(self, path: str) -> bool:
        ...
    
    @abstractmethod
    def list_files(self, directory: str) -> list[str]:
        ...
    
    @abstractmethod
    def get_adapter_name(self) -> str:
        ...