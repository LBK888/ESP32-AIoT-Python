from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_origins(value: str) -> tuple[str, ...]:
    return tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())


@dataclass(slots=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = Path("data")
    admin_user: str = "admin"
    admin_password: str | None = None
    session_hours: int = 12
    cookie_secure: bool = False
    allowed_origins: tuple[str, ...] = ("http://localhost:8000", "http://127.0.0.1:8000")
    mqtt_enabled: bool = False
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    testing: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "aquarium.sqlite3"

    @property
    def generated_admin_path(self) -> Path:
        return self.data_dir / "initial-admin.txt"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("AQUARIUM_HOST", "0.0.0.0"),
            port=int(os.getenv("AQUARIUM_PORT", "8000")),
            data_dir=Path(os.getenv("AQUARIUM_DATA_DIR", "data")).expanduser().resolve(),
            admin_user=os.getenv("AQUARIUM_ADMIN_USER", "admin"),
            admin_password=os.getenv("AQUARIUM_ADMIN_PASSWORD") or None,
            session_hours=max(1, min(168, int(os.getenv("AQUARIUM_SESSION_HOURS", "12")))),
            cookie_secure=_env_bool("AQUARIUM_COOKIE_SECURE"),
            allowed_origins=_split_origins(
                os.getenv(
                    "AQUARIUM_ALLOWED_ORIGINS",
                    "http://localhost:8000,http://127.0.0.1:8000",
                )
            ),
            mqtt_enabled=_env_bool("AQUARIUM_MQTT_ENABLED"),
            mqtt_host=os.getenv("AQUARIUM_MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.getenv("AQUARIUM_MQTT_PORT", "1883")),
            mqtt_username=os.getenv("AQUARIUM_MQTT_USERNAME") or None,
            mqtt_password=os.getenv("AQUARIUM_MQTT_PASSWORD") or None,
        )

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def bootstrap_password(self) -> tuple[str, bool]:
        if self.admin_password:
            return self.admin_password, False
        password = secrets.token_urlsafe(18)
        return password, True

