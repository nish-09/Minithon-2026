"""Central configuration. Every tunable (response windows, weights) lives here or in env vars."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEXA_", extra="ignore")

    database_url: str = "sqlite:///./nexa.db"
    jwt_secret: str = "dev-only-change-me-in-production-please-32b"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:3000"
    environment: str = "development"
    bcrypt_rounds: int = 12
    sweeper_interval_s: int = 5  # background escalation/expiry sweep; 0 disables

    # Optional LLM (falls back to deterministic rule-based NLU when unset / failing)
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5-20251001"

    # Optional LOCAL vision model for the first-aid camera check (Ollama, free, runs on this machine; pictures never leave it).
    # Used when no Anthropic key is set. Install once with: ollama pull qwen2.5vl:3b
    ollama_url: str = "http://localhost:11434"
    vision_model: str = "qwen2.5vl:3b"
    vision_timeout_s: float = 90.0  # the first call loads the model into memory

    # Optional server-side speech-to-text (OpenAI-compatible /audio/transcriptions endpoint)
    stt_url: str | None = None
    stt_api_key: str | None = None
    stt_model: str = "whisper-1"

    # Trusted-circle response windows, in seconds, per urgency. None => skip the circle wait.
    circle_window_normal_s: int = 300
    circle_window_urgent_s: int = 60
    circle_window_critical_s: int = 0
    circle_radius_km: float = 25.0
    community_radius_km: float = 10.0
    broadcast_size: int = 8  # helpers notified at once for urgent / critical requests
    normal_notify_count: int = 3  # helpers notified per batch for normal community requests
    max_search_radius_km: float = 40.0
    helper_window_normal_s: int = 180  # how long a notified community helper has to respond
    helper_window_urgent_s: int = 60
    helper_window_critical_s: int = 45
    emergency_number: str = "112"
    avg_speed_kmh: float = 28.0  # urban average used for ETA estimation
    request_expiry_minutes: int = 120

    # SmartMatch weights (sum is normalised at runtime)
    w_distance: float = 0.30
    w_skills: float = 0.25
    w_availability: float = 0.10
    w_trust: float = 0.20
    w_relationship: float = 0.10
    w_context: float = 0.05
    # Extra weight on distance / skills for critical requests
    critical_distance_boost: float = 1.5
    critical_skill_boost: float = 1.5

    # Help credits
    credit_reward_per_help: int = 10
    credit_cost_per_help: int = 10
    starting_credits: int = 20

    def helper_window(self, urgency: str) -> int:
        return {"normal": self.helper_window_normal_s, "urgent": self.helper_window_urgent_s,
                "critical": self.helper_window_critical_s}.get(urgency, self.helper_window_normal_s)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def circle_window(self, urgency: str) -> int:
        return {
            "normal": self.circle_window_normal_s,
            "urgent": self.circle_window_urgent_s,
            "critical": self.circle_window_critical_s,
        }.get(urgency, self.circle_window_normal_s)


@lru_cache
def get_settings() -> Settings:
    return Settings()
