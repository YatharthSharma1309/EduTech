from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_text_model: str = "qwen2.5:3b"
    ollama_vision_model: str = "qwen2.5vl:3b"

    pdf_upload_dir: str = "uploads/pdfs"
    output_dir: str = "outputs"

    render_dpi: int = 100  # PDF page render resolution

    cache_dir: str = "cache"          # where pre-processed PDF crops are stored
    cache_max_entries: int = 20       # LRU eviction limit (oldest removed first)

    cors_origins: str = "http://localhost:3000"  # comma-separated list

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
