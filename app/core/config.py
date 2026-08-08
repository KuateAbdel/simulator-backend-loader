"""
app/core/config.py
==================
Configuration du backend Loader. Aucun secret n'est jamais ecrit en dur :
tout provient de l'environnement ou du fichier .env local (jamais committe).

Les valeurs par defaut pointent exclusivement vers l'environnement TEST
FinZuu. C'est une garantie ENF-16 / R-06 : le Loader ne doit JAMAIS pouvoir
atteindre un environnement de production, meme par erreur de configuration.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Application -------------------------------------------------------
    app_name: str = "Loader FinZuu — Backend"
    app_version: str = "1.0.0"
    debug: bool = False

    # -- Persistance MongoDB (motor, cf. FZ-STACK-LOADER-2026-001 §5.3) ----
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "loader_finzuu"

    # -- Bootstrap Super-Admin (Phase 1 = Super-Admin UNIQUEMENT) ----------
    # Le compte est cree au premier demarrage s'il est absent en base.
    # must_change_password est pose a True : le mot de passe initial n'est
    # jamais un mot de passe durable.
    super_admin_email: str | None = None
    super_admin_password_initial: str | None = None

    # -- Fenetre de simulation (ENF-16 : 180 jours parametrable) -----------
    sim_start_date: date | None = None
    sim_end_date: date | None = None

    # -- Cibles externes : environnement TEST exclusivement (ENF-16, R-06) -
    faker_base_url: str = "https://faker.fintech4esg.com"
    faker_api_key: str | None = None

    user_service_base: str = "https://user-service.test.services.fintech4esg.com"
    config_service_base: str = "https://config-service.test.services.fintech4esg.com"
    identity_service_base: str = "https://identity-service.test.services.fintech4esg.com"
    account_service_base: str = "https://account-service.test.services.fintech4esg.com"
    company_service_base: str = "https://company-service.test.services.fintech4esg.com"
    product_service_base: str = "https://product-service.test.services.fintech4esg.com"
    depositary_service_base: str = "https://depositary-service.test.services.fintech4esg.com"
    client_service_base: str = "https://client-service.test.services.fintech4esg.com"
    collect_service_base: str = "https://collect-service.test.services.fintech4esg.com"

    # -- Credentials ROOT (D-DEP-7 : ROOT exclusif sur depositary-service) -
    root_username: str | None = None
    root_password: str | None = None

    # -- Client HTTP (httpx async, HTTP/2 negocie par APISIX 3.13.0) -------
    http_timeout_seconds: float = Field(default=15.0, gt=0)


settings = Settings()
