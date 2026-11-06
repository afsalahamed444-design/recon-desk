import os
import secrets
from pathlib import Path


class Settings:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./data/recon.db")
        if self.database_url.startswith("postgres://"):  # Render-style URL
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        # In dev a random secret per process is fine; production must set JWT_SECRET.
        self.jwt_secret = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
        self.jwt_hours = int(os.getenv("JWT_HOURS", "12"))
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.demo_password = os.getenv("DEMO_PASSWORD", "demo-pass-1234")
        self.seed_on_start = os.getenv("SEED_ON_START", "true").lower() == "true"
        self.seed_orders = int(os.getenv("SEED_ORDERS", "10000"))
        self.data_dir = Path(os.getenv("DATA_DIR", "./data"))
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "50"))
        self.cors = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
        self.tolerance = float(os.getenv("TOLERANCE_INR", "10"))
        self.return_window_days = int(os.getenv("RETURN_WINDOW_DAYS", "7"))


settings = Settings()
