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
    #: SemVer, regle de `docs/PLAN_SPRINTS.md` §5 : `1.0.0` = premiere livraison
    #: couvrant `CR-01` a `CR-12`. Le numero n'est pose que sur un increment dont
    #: la definition de terminé est atteinte — jamais sur une intention.
    #: `0.5.0` (14/08) : le CODE des modules Utilisateurs -> Population est
    #: complet et prouve (DRY_RUN 2000, 948 tests), l'API Super-Admin est
    #: entiere, la chaine CI/CD posee. Restent : VIE (`0.6.0`, arbitrages
    #: A-07/A-11/A-04) puis paliers REAL + recette (`1.0.0`).
    app_version: str = "0.5.0"
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

    # -- Session du Super-Admin du Loader (US-A1..A4) ----------------------
    #: Secret de signature des jetons de session. S'il est absent, un secret
    #: EPHEMERE est genere au demarrage : les sessions ne survivent alors pas
    #: a un redemarrage — accepte en developpement, journalise en warning.
    #: En production, le poser dans l'environnement.
    admin_jwt_secret: str | None = None
    #: Duree de vie d'une session — 4 h, alignee sur le jeton de la plateforme.
    admin_session_duree_heures: int = 4

    # -- Reinitialisation par email (US-A4 v2, Mailjet) --------------------
    #: Les TROIS valeurs sont requises pour que la route existe vraiment :
    #: sans elles, /admin/auth/mot-de-passe-oublie repond 503 NOMME — le
    #: reset est provisionne ou il n'est pas, jamais un envoi perdu en
    #: silence. L'expediteur doit etre une adresse VALIDEE du compte Mailjet
    #: (GET /v3/REST/sender), sinon Mailjet refuse l'envoi.
    mailjet_api_key: str | None = None
    mailjet_secret_key: str | None = None
    mailjet_expediteur: str | None = None

    # -- Fenetre de simulation (ENF-16 : 180 jours parametrable) -----------
    sim_start_date: date | None = None
    sim_end_date: date | None = None

    # -- Compression temporelle (Annexe D.3, EF-76) ------------------------
    # Un jour de SIMULATION n'est pas un jour REEL. Ces deux reglages sont
    # l'unique endroit ou le rapport entre les deux se decide.
    #
    #   INSTANTANE  86 400 s/jour — retro-datage. Les 180 jours restent etales
    #               sur 180 VRAIS jours dans le passe : c'est le mode de
    #               peuplement (`OBJ-04`, moins de 30 minutes d'ecriture).
    #   ACCELERE    0,2 a 60 s/jour — demonstration commerciale. A 10 s/jour,
    #               le cycle complet tient en une demi-heure de reunion.
    #   REALISTE    226,49 s/jour — le repli du script Duhamel.
    #
    # Le defaut est INSTANTANE : le Loader peuple, il n'anime pas.
    sim_mode_compression: str = "INSTANTANE"
    #: Lu UNIQUEMENT en mode ACCELERE. Les bornes de l'Annexe D.3 sont
    #: appliquees par `TempsSimulation`, pas ici.
    sim_secondes_par_jour: float = 1.0

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
    #: `V-01` — le 11e service. Il manquait au releve de version alors qu'il
    #: fait partie de l'ecosysteme au meme titre que les autres. L'URL suit la
    #: convention des neuf precedents ; `USSD_SERVICE_BASE` la corrige sans
    #: toucher au code si l'instance de test en expose une autre.
    ussd_service_base: str = "https://ussd-service.test.services.fintech4esg.com"
    #: `V-01` — decouverts le 24/08 dans les journaux de transparence des
    #: certificats, alors qu'ils tournent sur l'instance de test depuis
    #: juillet et aout. Le Loader les ignorait : un service absent du releve
    #: est un service dont personne ne voit ni l'etat ni le changement.
    bulk_paiement_service_base: str = (
        "https://bulk-paiement-service.test.services.fintech4esg.com"
    )
    notification_service_base: str = (
        "https://notification-service.test.services.fintech4esg.com"
    )

    # -- Credentials ROOT (D-DEP-7 : ROOT exclusif sur depositary-service) -
    root_username: str | None = None
    root_password: str | None = None

    # -- Client HTTP (httpx async, HTTP/2 negocie par APISIX 3.13.0) -------
    http_timeout_seconds: float = Field(default=15.0, gt=0)

    # -- CORS — l'origine du frontend de Zidane (US : le Loader est une web
    #    app, il fait le BACKEND, Zidane le frontend Next.js). Si le frontend
    #    vit sur un AUTRE domaine que cette API, le navigateur exige des
    #    en-tetes CORS : sans eux, chaque appel du frontend est bloque.
    #    Liste d'origines EXACTES separees par des virgules (schema + hote,
    #    jamais `*` avec des credentials — regle de securite du navigateur).
    #    Vide par defaut : aucune origine croisee autorisee, le choix est
    #    EXPLICITE en production (`CORS_ALLOW_ORIGINS=https://...`).
    cors_allow_origins: str = ""

    @property
    def origines_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    # -- Anti-brute-force (I-AUTH-11) — confiance au reverse-proxy ---------
    #    L'IP de throttling doit etre la VRAIE IP du client. Derriere nginx,
    #    elle arrive dans `X-Forwarded-For` ; en direct, c'est la socket. On ne
    #    lit l'en-tete QUE si on declare le proxy de confiance : sinon un
    #    attaquant forge `X-Forwarded-For` et se donne une IP neuve a chaque
    #    coup, contournant le throttle. FAUX par defaut = sur (on n'accorde la
    #    confiance qu'explicitement, une fois le proxy en place).
    faire_confiance_proxy: bool = False


settings = Settings()
