from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_text_model: str = "llama3.2"
    ollama_vision_model: str = "qwen2.5vl:3b"

    pdf_upload_dir: str = "uploads/pdfs"
    output_dir: str = "outputs"

    render_dpi: int = 100  # PDF page render resolution

    cors_origins: str = "http://localhost:3000"  # comma-separated list

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
