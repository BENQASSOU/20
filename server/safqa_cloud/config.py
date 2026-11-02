"""Settings, read from environment variables (see render.yaml / .env.example)."""

import os


def _bool(name, default):
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "oui", "on")


class Settings:
    def __init__(self, **over):
        env = os.environ.get
        self.env = over.get("env", env("SAFQA_ENV", "development"))
        self.database_url = over.get("database_url", env("DATABASE_URL", "sqlite:///./safqa_cloud.db"))
        self.data_key = over.get("data_key", env("SAFQA_DATA_KEY", ""))
        if not self.data_key and self.env != "production":
            self.data_key = "development-only-key-do-not-use"
        self.admin_emails = {e.strip().lower() for e in over.get(
            "admin_emails", env("SAFQA_ADMIN_EMAILS", "")).split(",") if e.strip()}
        self.anthropic_key = over.get("anthropic_key", env("ANTHROPIC_API_KEY", ""))
        self.license_secret = over.get("license_secret", env("SAFQA_LICENSE_SECRET", ""))
        self.trust_proxy = over.get("trust_proxy", _bool("SAFQA_TRUST_PROXY", True))
        self.allow_signup = over.get("allow_signup", _bool("SAFQA_ALLOW_SIGNUP", True))
        self.storage_mb = int(over.get("storage_mb", env("SAFQA_ORG_STORAGE_MB", "1024")))
        self.session_days = int(over.get("session_days", env("SAFQA_SESSION_DAYS", "60")))
        self.idle_days = int(over.get("idle_days", env("SAFQA_SESSION_IDLE_DAYS", "21")))
        self.trial_days = int(over.get("trial_days", env("SAFQA_TRIAL_DAYS", "14")))
        self.smtp = {"host": env("SMTP_HOST", ""), "port": int(env("SMTP_PORT", "587")),
                     "user": env("SMTP_USER", ""), "password": env("SMTP_PASSWORD", ""),
                     "sender": env("SMTP_FROM", env("SMTP_USER", ""))}
        self.smtp.update(over.get("smtp", {}))
        self.public_name = env("SAFQA_PUBLIC_NAME", "Safqa Cloud")

    def check(self):
        problems = []
        if self.env == "production":
            if len(self.data_key) < 32:
                problems.append("SAFQA_DATA_KEY doit contenir au moins 32 caractères aléatoires.")
            if self.database_url.startswith("sqlite") and not os.environ.get("SAFQA_ALLOW_SQLITE"):
                problems.append("DATABASE_URL doit pointer vers PostgreSQL en production.")
        return problems
