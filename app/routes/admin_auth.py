"""
app/routes/admin_auth.py
========================
Session du Super-Admin du LOADER — `US-A1` a `US-A4` du backlog
(`docs/BACKLOG_SUPER_ADMIN.md`, page Confluence 67665922).

A ne JAMAIS confondre avec le Super-Admin de la plateforme FinZuu : celui-ci
vit dans NOTRE MongoDB (`super_admin_accounts`), celui-la est un groupe RBAC
de user-service (`MODELE_UTILISATEURS.md` §1).

L'EMAIL EST VALIDE, PAS UN STRING — exigence de Yaniv du 13/08, et c'est la
doctrine du projet appliquee a nous-memes : la plateforme accepte n'importe
quoi dans ses champs (`D-IDN-1`, `FRA-222`...), et le Loader valide ce que le
serveur ne valide pas. On ne va pas etre plus laxiste avec notre propre porte
d'entree que nous le sommes avec les leurs — `EmailStr` (email-validator),
normalise en minuscules, ou 422.

LE MOT DE PASSE OUBLIE (`US-A4`) — deux niveaux, dits franchement :

1. **Par email (v2, LIVRE le 14/08)** : `POST /mot-de-passe-oublie` envoie un
   CODE a 8 chiffres via Mailjet (cles fournies par Yaniv), valide 15 min,
   5 essais maximum. `POST /reinitialiser` le consomme avec le nouveau mot
   de passe. La reponse du premier est TOUJOURS 202 quand le service est
   provisionne — confirmer qu'un email existe serait offrir l'enumeration
   des comptes a un attaquant (meme doctrine que le 401 muet du login).
   Si les cles MAILJET_* ne sont pas posees : 503 NOMME, jamais un envoi
   silencieusement perdu.
2. **Sur le serveur (v1, conserve)** : `scripts/reinitialiser_admin.py`,
   execute par l'operateur — l'acces au serveur est la preuve d'autorite
   (modele GitLab `gitlab-rake`). Reste le recours si Mailjet est mort.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Annotated
from uuid import NAMESPACE_OID, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.clients import mailjet
from app.core import politique_mot_de_passe as politique
from app.core.config import settings
from app.core.politique_mot_de_passe import LONGUEUR_MDP_MIN
from app.core.security import emettre_jeton_admin
from app.repositories.audit_trail import AuditTrailRepository
from app.repositories.auth_throttle import AuthThrottleRepository
from app.repositories.super_admin import SuperAdminRepository
from app.routes.dependances import SessionAdmin, session_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/auth", tags=["admin — session"])

#: Run SENTINELLE des evenements d'administration hors-run (cf. admin_comptes).
RUN_ADMIN = UUID(int=0)


def _ip_client(request: Request) -> str:
    """La VRAIE IP du client, pour le throttle par source (I-AUTH-11).

    Derriere un reverse-proxy declare de confiance, elle est dans le PREMIER
    hop de `X-Forwarded-For` (les suivants sont ajoutes par nos propres
    couches). Sans cette confiance EXPLICITE, on ignore l'en-tete — sinon un
    attaquant le forge et se donne une IP neuve a chaque tentative. En dernier
    recours (pas de socket : ASGI de test), on renvoie une valeur stable."""
    if settings.faire_confiance_proxy:
        transmis = request.headers.get("x-forwarded-for", "")
        premier = transmis.split(",")[0].strip()
        if premier:
            return premier
    return request.client.host if request.client else "inconnu"


def _refus_si_throttle(bloque: bool, retry: int) -> None:
    """429 GENERIQUE + `Retry-After` si un cooldown court. Le message ne nomme
    ni le compte ni la cause exacte : un 429 identique pour un email existant
    ou non (anti-enumeration, CWE-204)."""
    if bloque:
        raise HTTPException(
            status_code=429,
            detail="trop de tentatives — patientez avant de réessayer",
            headers={"Retry-After": str(retry)},
        )

#: Le code de reinitialisation : 8 chiffres, 15 minutes, 5 essais. Un code
#: court est acceptable PARCE QUE la fenetre est courte et les essais bornes.
CODE_RESET_VALIDITE_SECONDES = 15 * 60
CODE_RESET_ESSAIS_MAX = 5


def _hacher_code(code: str) -> str:
    """SHA-256 suffit : le code a 15 min de vie et 5 essais — le cout d'un
    bcrypt ne protegerait rien de plus ici."""
    return hashlib.sha256(code.encode()).hexdigest()


class DemandeConnexion(BaseModel):
    """`US-A1` — l'email est un EMAIL (RFC), jamais un string libre."""

    email: EmailStr
    mot_de_passe: str = Field(min_length=1)


class ReponseSession(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — le TYPE du jeton OAuth2, pas un secret
    expires_in: int
    #: `US-A2` — quand vrai, la seule route ouverte est /admin/auth/password.
    must_change_password: bool
    #: RBAC — le role du compte, remonte des le login pour que le front projette
    #: le bon dashboard sans avoir a decoder le JWT. La verite d'autorisation
    #: reste le jeton (verifie a l'API) ; ceci n'est qu'une commodite d'affichage.
    role: str


class DemandeChangementMdp(BaseModel):
    ancien: str = Field(min_length=1)
    nouveau: str = Field(min_length=LONGUEUR_MDP_MIN)


def _exiger_mot_de_passe_conforme(nouveau: str, *, email: str) -> None:
    """Applique l'invariant I-AUTH-9. Leve 422 avec la LISTE des exigences non
    tenues — le front les affiche telles quelles (« choisissez-en un autre »).

    N.B. : on NE verifie PAS l'unicite inter-comptes du mot de passe — voir
    l'en-tete de `politique_mot_de_passe` (oracle interdit, NIST 800-63B)."""
    raisons = politique.evaluer(nouveau, email=email)
    if raisons:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "mot de passe refuse — choisissez-en un autre",
                "exigences": raisons,
            },
        )


@router.post("/login", response_model=ReponseSession)
async def login(demande: DemandeConnexion, request: Request) -> ReponseSession:
    """`US-A1` — la connexion, protegee du brute-force (I-AUTH-11).

    Le refus est VOLONTAIREMENT muet sur sa cause : dire « email inconnu »
    confirmerait l'existence des comptes a un attaquant. 401, un seul message.

    Anti-brute-force : deux clés de throttle, l'IDENTIFIANT soumis et l'IP
    SOURCE. Si l'une est en cooldown, on refuse en 429 AVANT toute verification
    (on ne brule pas de scrypt pour un attaquant, et on ne verrouille JAMAIS le
    compte — cf. `auth_throttle`). Un login reussi efface les deux compteurs.
    """
    throttle = AuthThrottleRepository()
    identifiant = str(demande.email).strip().lower()
    ip = _ip_client(request)

    for cle in (f"id:{identifiant}", f"ip:{ip}"):
        bloque, retry = await throttle.etat(cle)
        _refus_si_throttle(bloque, retry)

    compte = await SuperAdminRepository().authentifier(
        str(demande.email), demande.mot_de_passe
    )
    if compte is None:
        # Echec compte SUR LES DEUX cles : l'identifiant vise ET la source.
        await throttle.enregistrer_echec(f"id:{identifiant}")
        await throttle.enregistrer_echec(f"ip:{ip}")
        raise HTTPException(status_code=401, detail="identifiants invalides")

    # Reussite : auto-cicatrisation des deux compteurs.
    await throttle.reinitialiser(f"id:{identifiant}")
    await throttle.reinitialiser(f"ip:{ip}")

    # Tracabilite (Yaniv 20/08) : horodater la connexion et l'inscrire au
    # JOURNAL (visible du seul Super-Admin). Tracer ne doit JAMAIS empecher de
    # se connecter — d'ou le try/except qui avale et journalise.
    try:
        await SuperAdminRepository().marquer_connexion(compte.email)
        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Session",
            entity_id=uuid5(NAMESPACE_OID, f"loader-login:{compte.email}"),
            operation="LOGIN",
            cible="loader /admin/auth/login",
            payload={"par": compte.email, "role": compte.role},
        ) as suivi:
            suivi.reussi({"email": compte.email})
    except Exception as erreur:  # la trace ne bloque JAMAIS le login
        logger.warning("trace de connexion ignoree : %s", type(erreur).__name__)

    portee = "password_only" if compte.must_change_password else "admin"
    jeton, duree = emettre_jeton_admin(compte.email, portee=portee, role=compte.role)
    return ReponseSession(
        access_token=jeton,
        expires_in=duree,
        must_change_password=compte.must_change_password,
        role=compte.role,
    )


@router.post("/password", response_model=ReponseSession)
async def changer_mot_de_passe(
    demande: DemandeChangementMdp,
    session: Annotated[SessionAdmin, Depends(session_admin)],
) -> ReponseSession:
    """`US-A2` — le changement de mot de passe.

    Accessible aux DEUX portees : c'est precisement la route que la portee
    `password_only` existe pour atteindre. L'ancien mot de passe est re-verifie
    — un jeton vole ne suffit pas a changer le mot de passe.
    """
    depot = SuperAdminRepository()
    compte = await depot.authentifier(session.email, demande.ancien)
    if compte is None:
        raise HTTPException(status_code=401, detail="ancien mot de passe invalide")
    if demande.nouveau == demande.ancien:
        raise HTTPException(
            status_code=422,
            detail="le nouveau mot de passe doit differer de l'ancien",
        )
    _exiger_mot_de_passe_conforme(demande.nouveau, email=session.email)

    await depot.changer_mot_de_passe(session.email, demande.nouveau)
    # La session repart PLEINE : l'obligation est levee, le jeton l'atteste.
    # Le role du compte est REPORTE — sans lui, le jeton retomberait sur le
    # defaut super_admin (escalade). Le mot de passe change, pas le role.
    jeton, duree = emettre_jeton_admin(session.email, portee="admin", role=compte.role)
    return ReponseSession(
        access_token=jeton, expires_in=duree, must_change_password=False, role=compte.role
    )


class DemandeVerifMotDePasse(BaseModel):
    mot_de_passe: str
    #: Optionnel — permet de refuser un mot de passe qui contient l'email.
    email: EmailStr | None = None


@router.post("/politique-mot-de-passe")
async def verifier_politique_mot_de_passe(
    demande: DemandeVerifMotDePasse,
) -> dict[str, object]:
    """Valide un mot de passe candidat en TEMPS REEL (UX interactive I-AUTH-9).

    Ouvert et sans etat : c'est une fonction PURE du candidat (aucun compte
    n'est consulte), donc elle ne peut rien reveler sur les utilisateurs — a
    l'oppose exact d'un oracle « ce mot de passe est deja pris ». Le front s'en
    sert pour afficher « choisissez-en un autre » avant meme la soumission ;
    l'enforcement reste 422 cote serveur, seul juge.
    """
    raisons = politique.evaluer(
        demande.mot_de_passe, email=str(demande.email) if demande.email else None
    )
    return {
        "acceptable": not raisons,
        "exigences": raisons,
        "longueur_min": LONGUEUR_MDP_MIN,
    }


# --------------------------------------------------------------------------
# `US-A4` v2 — reinitialisation par email (Mailjet)
# --------------------------------------------------------------------------


class DemandeMotDePasseOublie(BaseModel):
    email: EmailStr


class DemandeReinitialisation(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1)
    nouveau: str = Field(min_length=LONGUEUR_MDP_MIN)


@router.post("/mot-de-passe-oublie", status_code=202)
async def mot_de_passe_oublie(
    demande: DemandeMotDePasseOublie, request: Request
) -> dict[str, object]:
    """`US-A4` v2 — envoie un code de reinitialisation par email.

    202 TOUJOURS quand le service est provisionne, que le compte existe ou
    non : confirmer l'existence d'un email offrirait l'enumeration des
    comptes (meme doctrine que le 401 muet du login). L'echec d'ENVOI est
    journalise en warning mais ne change pas la reponse, pour la meme raison.

    Anti-email-bombing (I-AUTH-11) : on borne les demandes PAR SOURCE. Au-dela
    du seuil, on ne DECLENCHE PLUS d'envoi — mais on garde le 202 muet (ne rien
    reveler). Chaque appel incremente le compteur de la source ; l'inactivite
    le purge.
    """
    if not mailjet.provisionne():
        raise HTTPException(
            status_code=503,
            detail=(
                "reinitialisation par email non provisionnee — poser "
                "MAILJET_API_KEY, MAILJET_SECRET_KEY et MAILJET_EXPEDITEUR ; "
                "recours : scripts/reinitialiser_admin.py sur le serveur"
            ),
        )

    throttle = AuthThrottleRepository()
    cle_source = f"reset-req:ip:{_ip_client(request)}"
    source_saturee, _ = await throttle.etat(cle_source)
    await throttle.enregistrer_echec(cle_source)

    depot = SuperAdminRepository()
    email = str(demande.email).strip().lower()
    compte = await depot.par_email(email)
    if compte is not None and not source_saturee:
        code = f"{secrets.randbelow(10**8):08d}"
        await depot.poser_code_reinitialisation(
            email, _hacher_code(code), time.time() + CODE_RESET_VALIDITE_SECONDES
        )
        await mailjet.envoyer_email(
            email,
            "FinZuu Loader — code de réinitialisation",
            (
                f"Votre code de réinitialisation : {code}\n\n"
                f"Il expire dans {CODE_RESET_VALIDITE_SECONDES // 60} minutes "
                f"({CODE_RESET_ESSAIS_MAX} essais maximum).\n"
                "Si vous n'êtes pas à l'origine de cette demande, ignorez ce "
                "message — votre mot de passe actuel reste valable."
            ),
        )
    return {
        "detail": "si un compte existe pour cet email, un code a été envoyé",
        "validite_minutes": CODE_RESET_VALIDITE_SECONDES // 60,
    }


@router.post("/reinitialiser", response_model=ReponseSession)
async def reinitialiser_par_code(
    demande: DemandeReinitialisation, request: Request
) -> ReponseSession:
    """`US-A4` v2 — consomme le code et pose le nouveau mot de passe.

    Le refus est GENERIQUE (401, un seul message) : distinguer « email
    inconnu » / « code faux » / « code expire » renseignerait un attaquant.
    Le mot de passe qui en sort est DURABLE (choisi par son proprietaire) —
    la session repart pleine, comme apres `US-A2`.

    Double borne anti-devinette du code : le code lui-meme meurt a 5 essais
    (per-code), ET la SOURCE est throttlee (I-AUTH-11) pour empecher d'enchainer
    les codes depuis une meme origine. 429 generique si la source est saturee.
    """
    throttle = AuthThrottleRepository()
    cle_source = f"reset-code:ip:{_ip_client(request)}"
    bloque, retry = await throttle.etat(cle_source)
    _refus_si_throttle(bloque, retry)

    refus = HTTPException(status_code=401, detail="code invalide ou expiré")
    depot = SuperAdminRepository()
    email = str(demande.email).strip().lower()
    compte = await depot.par_email(email)
    if compte is None or compte.code_reset_hash is None or compte.code_reset_expire is None:
        await throttle.enregistrer_echec(cle_source)
        raise refus
    if time.time() > compte.code_reset_expire:
        await throttle.enregistrer_echec(cle_source)
        raise refus
    if compte.code_reset_essais >= CODE_RESET_ESSAIS_MAX:
        await throttle.enregistrer_echec(cle_source)
        raise refus
    if not hmac.compare_digest(compte.code_reset_hash, _hacher_code(demande.code)):
        # L'essai rate CONSOMME — 5 echecs tuent le code, meme encore valide.
        await depot.incrementer_essais_reset(email)
        await throttle.enregistrer_echec(cle_source)
        raise refus
    if demande.nouveau == demande.code:
        raise HTTPException(
            status_code=422, detail="le mot de passe ne peut pas être le code lui-même"
        )
    _exiger_mot_de_passe_conforme(demande.nouveau, email=email)

    await depot.changer_mot_de_passe(email, demande.nouveau)
    await depot.effacer_code_reinitialisation(email)
    await throttle.reinitialiser(cle_source)  # reussite -> auto-cicatrisation
    # Role REPORTE (cf. US-A2) : ne jamais laisser le jeton retomber sur le
    # defaut super_admin apres un reset.
    jeton, duree = emettre_jeton_admin(email, portee="admin", role=compte.role)
    return ReponseSession(
        access_token=jeton, expires_in=duree, must_change_password=False, role=compte.role
    )
