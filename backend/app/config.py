from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upload_dir: Path = Path("./storage/batches")
    max_file_size_mb: int = 2048
    max_batch_size_mb: int = 10240
    file_conversion_timeout_seconds: int = 300
    temp_file_ttl_hours: int = 24
    enable_ocr: bool = False
    enable_pandoc_fallback: bool = False
    enable_tika_fallback: bool = False
    enable_libreoffice_fallback: bool = False
    enable_zip_extraction: bool = True
    ocr_languages: str = "eng+kor"
    tesseract_cmd: str | None = None
    tesseract_tessdata_dir: Path | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_batch_size_bytes(self) -> int:
        return self.max_batch_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
