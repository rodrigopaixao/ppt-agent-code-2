from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://openrouter.ai/api"
    anthropic_model: str = "anthropic/claude-sonnet-4.5"
    pptx_template_path: Path = Path("assets/templates/client-a-template.pptx")
    pptx_data_dir: Path = Path("data")
    web_origin: str = "http://localhost:3000"
    max_upload_bytes: int = 15 * 1024 * 1024
    max_extracted_chars: int = 120_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.root_dir / path


settings = Settings()
