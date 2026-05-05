from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_text_model: str = "llama3.2"
    ollama_vision_model: str = "qwen2.5vl:7b"

    pdf_upload_dir: str = "uploads/pdfs"
    image_dir: str = "uploads/images"
    output_dir: str = "outputs"

    render_dpi: int = 150  # PDF page render resolution

    class Config:
        env_file = ".env"


settings = Settings()
