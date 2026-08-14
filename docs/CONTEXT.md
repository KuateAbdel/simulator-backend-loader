# Contexte Projet — Simulator Backend (Loader FinZuu)

## Stack technique obligatoire
Python 3.12, FastAPI, httpx (async), MongoDB via motor, Pydantic v2, PyJWT, uv/ruff/mypy/pytest.
Frontend séparé (Next.js, Zidane) — hors périmètre de ce repo.

## Ce que ce projet fait
Orchestrateur HTTP. Consomme Faker fintech4esg (clients, historique credit, scoring) et 9 microservices FinZuu (user, config, identity, account, product, company, depositary, client, collect). Aucune logique métier propre — génère un écosystème de démonstration : 2000 clients, 4 pays (CM/CI/BF/SN), fenêtre temporelle de 180 jours.

## 6 schémas MongoDB à respecter exactement
- faker_consumption_ledger : {_id: client_id Faker, consumed_at, consumed_for, resulting_entity_id, country_code}
- lenders_registry : {_id, company_id, lender_type, country_code, capital/interest/penalty/taxe_account_id}
- loader_runs : {_id: run_id, sim_start_date, sim_end_date, status, mode, checkpoints, **configuration**}

> **7e champ ajoute le 09/08/2026, decision D-10.** Des que la volumetrie devient
> parametrable, le `run_id` ne suffit plus a reproduire une execution. La
> configuration complete — pays actifs, surcharges, repartition, surcouche
> referentielle, ecarts au CDC — est figee au lancement et persistee ici.
> Sans elle, `ENF-15` est perdue et `CR-04` invérifiable. Elle n'est PAS dans
> `checkpoints` : ceux-ci changent pendant l'execution, la configuration non.
- audit_trail : {_id, run_id, entity_type, entity_id, action, before, after, timestamp}
- super_admin_accounts : {_id, email, password_hash, must_change_password}
- org_hierarchy : {_id, run_id, niveau (BRANCHE|AGENCE|KIOSQUE|**AGENT**), parent_id, company_id, name, country_code, region_id, city_id, district_id, depositary_id, **user_id**}

> **Niveau AGENT ajoute le 09/08/2026, decision D-11.** Le CDC §6 decrit SIX
> niveaux ; nous n'en modelisions que cinq. L'Agent existe cote serveur — c'est
> un User — mais SON RATTACHEMENT AU KIOSQUE n'existe nulle part : `User` porte
> `company_id` et `identity`, jamais de reference vers un Depositaire. Sans ce
> niveau, « quels Agents dans ce Kiosque ? » reste sans reponse, et `UC-09`
> point 4 est invérifiable.

> **Ajoutée le 08/08/2026, décision (b) sur Branche/Agence.** company-service n'expose
> aucune route pour Branche ni Agence, et son enum CompanyType ne comporte aucune valeur
> BRANCH — les matérialiser en Companies filles ferait exploser le budget de 12-20
> Companies fixé par UC-07. Elles restent donc des niveaux logiques internes.
> Cette collection n'est pas un confort : sans elle, **CR-02 devient invérifiable**, ce
> critère de recette exigeant de contrôler que « chaque Kiosque a un District valide,
> chaque Agence une Ville valide ». Seul le niveau KIOSQUE a une contrepartie serveur
> (le Dépositaire, créé avec company_id = l'IMF racine).

## 5 disciplines défensives critiques, NON NEGOCIABLES
- D-FAKER-1 : jamais réutiliser un client_id Faker déjà consommé (vérifier faker_consumption_ledger avant chaque tirage)
- D-CMP-2 : creation d'une Company cascade automatiquement vers identity-service (owner). MAIS admin_email NE cree JAMAIS de User — le faire explicitement via user-service (register -> password/f/change -> login)
- D-DEP-7 (FRA-205) : depositary-service n'a AUCUNE restriction RBAC reelle — utiliser exclusivement le token ROOT pour toute ecriture
- D-PRD-4/D-PRD-9 : categorie "Any" doit etre splittee en 2 creations (INDIVIDUAL + CORPORATE). Jamais dupliquer un produit deja existant (GET avant POST)
- Jamais de montant negatif/nul envoye a collect-service (rejet HTTP apparent mais mutation reelle silencieuse)

## Bootstrap Super-Admin
Variables d'environnement SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD_INITIAL. Creation automatique au demarrage si absent en base.

## Les trois domaines — à ne jamais confondre

| Domaine | À qui | Ce qu'il expose |
|---|---|---|
| `faker.fintech4esg.com` | **Faker** (Oti, fintech4esg) | les 15 endpoints de payloads simulés |
| `<service>.test.services.fintech4esg.com` | les **9 microservices FinZuu** | leur OpenAPI / Swagger |
| **`simul.fintech4esg.com`** | **notre serveur** | Loader (backend + frontend + BDD + SIEM), Newsletter, SendMail |

### Notre cible — `simul.fintech4esg.com`

Source : `FZ-INFRA-SIMUL-2026-001` (Confluence TST 52330498).

| | |
|---|---|
| Frontend | `simul.fintech4esg.com` |
| Backend | `simul.fintech4esg.com` |
| Serveur | NetCup, **ARM64**, 6 vCPU / 8 Go / 256 Go, `152.53.53.139` |
| OS | Debian 13 Trixie minimal |
| Reverse proxy | **Traefik** — ADR-02, Nginx explicitement rejeté |
| Colocataires | Newsletter, SendMail |
| Statut | **vierge, non provisionné** au 18/07/2026 |

> **Deux corrections du 11/08.**
>
> 1. Le CDC écrit trois fois `loader.fintech4esg.com` (§268, `ENF-11`, `H-04`).
>    **Ce lien est incorrect** — arbitrage de Yaniv. Le domaine réel est
>    `simul.*`. `ENF-11` se lit donc : déploiement sur `simul.fintech4esg.com`
>    avec authentification requise.
> 2. Ce document et `app/main.py` annonçaient « le Nginx déjà en place sur
>    152.53.118.110 ». **Ni cette IP ni Nginx n'existent dans la documentation
>    d'infrastructure** : le reverse proxy retenu est Traefik, l'IP est
>    `152.53.53.139`, et le serveur n'est pas encore provisionné.

**Contrainte qui en découle, et elle est dure : le serveur est ARM64.** Les
images Docker doivent être multi-architecture (`linux/amd64` + `linux/arm64`),
sinon elles ne démarrent pas (piège `P11`, `ADR-13`). C'est déjà la raison du
choix de `scrypt` dans `app/core/security.py` — bibliothèque standard, aucune
extension compilée à faire exister sur `linux_aarch64`.
