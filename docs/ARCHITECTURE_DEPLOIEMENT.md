# Architecture de déploiement — conception senior (14/08/2026)

> Rédigé en tant que lead SysAdmin / DevOps / DevSecOps / Ingénieur, sur des
> faits **mesurés** (reconnaissance SSH + doc VPS du 24/03), sans supposition.
> Le Loader est le **BACKEND** (nous). Le frontend Next.js est celui de Zidane
> (nous ne le déployons jamais). Ce document fige l'analyse ; une seule
> décision reste ouverte (§2), elle t'appartient.

---

## 1. Le terrain, tel qu'il EST (mesuré)

Serveur **partagé** `152.53.118.110` — Netcup, Ubuntu 24.04 **ARM64**, 10 vCPU,
16 Go RAM (12 libres), 460 Go libres, **pas de swap**. Il fait déjà tourner
**3 projets critiques** qu'on ne touche sous aucun prétexte :

| Projet | Domaines | Conteneurs | Réseau Docker |
|---|---|---|---|
| ERPNext CRM | `crm.finzuu.com` | 8 | `erpnext-production_erpnext-net` |
| Nextcloud Talk/Collabora | `signaling/recording/collabora.finzuu.com` | 3 | `finzuu_default` |
| Newsletter (Zidane) | `news.fintech4esg.com` + `news.api.fintech4esg.com` | 5 | `newsletter-net` |

Faits structurants :
- **nginx est sur le HOST** (systemd, `enabled` au boot) — **seul pont**
  Internet→conteneurs. Il route par `server_name` vers des ports loopback.
- **Le port 8000 est PRIS** (`finzuu-talk-recording`). Le Loader prend **8003**.
- **Réseau `loader-net` déjà créé** par Yaniv (vide, prêt) → on l'adopte.
- **User `apps`** (groupes `sudo`+`docker`) — c'est LUI qui déploie, jamais root.
- Convention maison **prouvée par la Newsletter** : `X.fintech4esg.com` =
  frontend, `X.api.fintech4esg.com` = backend. Deux domaines, deux conteneurs.

---

## 2. ⚠️ LA SEULE DÉCISION OUVERTE — le mapping des domaines

Frontend et backend **doivent** être deux origines distinctes (c'est le
standard : deux équipes, deux dépôts, deux cadences de déploiement, CORS net).
La seule question : **quel domaine pour quel service ?** Deux mondes cohérents :

**Option B — la convention maison (RECOMMANDÉE)**
- `simul.fintech4esg.com` → **frontend** (Zidane)
- `simul.api.fintech4esg.com` → **backend** (Loader + Swagger)
- Identique à la Newsletter. À faire : vhost + certificat pour `simul.api`
  (le DNS résout déjà → `certbot` immédiat).

**Option A — ce que tu avais posé au départ**
- `simul.fintech4esg.com` → **backend** (Loader + Swagger) — vhost + cert déjà là
- Frontend de Zidane → sur un autre sous-domaine (`app.simul…`, à créer)

**Recommandation senior : Option B.** Raison : elle est *déjà* la convention
de ton serveur (Newsletter), donc zéro surprise pour quiconque reprend le
serveur ; elle met l'API sur le sous-domaine `.api` que tu as **déjà** préparé
dans le DNS ; et elle laisse le domaine « nu » au produit visible (le
frontend), ce qui est l'usage attendu par un intégrateur. Techniquement, mettre
le backend sur `simul.api` **ne pose AUCUN problème** : les deux domaines
pointent sur le même serveur, nginx tranche par `server_name`.

> **Cette décision ne change PAS le code** : le port (8003), les conteneurs,
> le CORS (piloté par env) sont identiques dans les deux cas. Elle ne change
> que le `server_name` du vhost et l'hôte du certificat. On peut donc tout
> préparer et ne fixer que cette ligne au dernier moment.

---

## 3. Topologie des conteneurs (identique quel que soit le domaine)

```
                      INTERNET (443, TLS Let's Encrypt)
                                  │
                    nginx HOST (systemd) — routage par server_name
                                  │  proxy_pass 127.0.0.1:8003
        ┌─────────────────── loader-net (Docker, isolé) ───────────────────┐
        │                                                                   │
        │   conteneur « loader »                 conteneur « mongo »        │
        │   FastAPI/uvicorn (ARM64)  ──────────► Mongo 7                    │
        │   127.0.0.1:8003:8000                  (AUCUN port publié)        │
        │   non-root, HEALTHCHECK /health        volume: loader_mongo_data  │
        └───────────────────────────────────────────────────────────────────┘
```

- **2 conteneurs, pas plus** : l'API et SA mémoire. `restart: unless-stopped`.
- **Mongo n'expose aucun port** — joignable seulement par le loader, dans le
  réseau. Sa mémoire (registre Faker, arbre, journal, config) vit dans le
  **volume nommé** — le perdre = perdre CR-03, la purge, la traçabilité.
- **loader** publie sur `127.0.0.1:8003` uniquement — jamais `0.0.0.0`. Seul
  nginx l'atteint ; le monde passe par le 443.
- **Image** : construite **nativement sur le serveur** (ARM64) — pas de
  cross-build depuis la machine de dev. `docs/reference/` embarqué (le
  classeur, chemins relatifs). `.dockerignore` en **liste blanche** : tests,
  `.env`, docs de travail ne PEUVENT pas entrer dans l'image.

---

## 4. Sécurité — la lecture DevSecOps

| Sujet | Décision | Pourquoi |
|---|---|---|
| Swagger `/docs`, `/openapi.json` | **public** | Zidane en a besoin en ligne ; toutes les ACTIONS sont derrière JWT — seul le schéma est exposé |
| CORS | **origines explicites** par env (`CORS_ALLOW_ORIGINS`), jamais `*` | le frontend est sur un autre domaine → sans CORS, le navigateur bloque tout. Ajouté + testé le 14/08 |
| `ADMIN_JWT_SECRET` | **obligatoire** en prod | sinon secret éphémère : toutes les sessions meurent à chaque redéploiement |
| Secrets | jamais dans Git, jamais dans l'image, jamais dans Mongo, jamais dans le journal | `.dockerignore` liste blanche ; ils vivent dans le `.env` du serveur |
| Accès serveur | clé SSH **dédiée** pour l'user `apps`, jamais le mot de passe root | l'audit VPS classe « SSH root password » en risque CRITIQUE — on ne l'aggrave pas |
| Mongo | aucun port publié | la mémoire n'est joignable que par le loader |
| Secrets des AUTRES projets | vus pendant la recon, **jamais copiés ni committés** | hors périmètre absolu |

---

## 5. CI/CD — le flux, déjà en place

```
git push main ─► CI (GitHub Actions)                 ─► CD (si CI verte)
                 ruff + mypy strict + 951 tests          SSH → serveur (apps)
                 contre un vrai MongoDB de service        git merge --ff-only
                 « ce qui ne passe pas ne part pas »      docker compose up -d --build
                                                          curl /health (preuve, pas déduction)
```

- CD armé, hôte vérifié par **empreinte** (jamais `StrictHostKeyChecking=no`),
  **un seul déploiement à la fois** (concurrency), rollback par `git revert`
  (jamais de force-push sur main, branche protégée).
- Build ARM64 natif sur le serveur.

---

## 6. Ce dont j'ai besoin de TOI — précisément

1. **La décision §2** (mapping des domaines) — la seule qui bloque le reste.
2. **Une clé SSH dédiée** pour l'user `apps` + **4 secrets GitHub**
   (`DEPLOY_HOST/USER/SSH_KEY/KNOWN_HOSTS`) — commandes dans `DEPLOIEMENT.md` §3.
3. **Le `.env` de production** rempli sur le serveur : `ADMIN_JWT_SECRET`
   (`openssl rand -hex 32`), compte bootstrap, `FAKER_API_KEY`, credentials
   ROOT, et **`CORS_ALLOW_ORIGINS` = l'origine du frontend de Zidane**.
4. **L'origine exacte du frontend de Zidane** (ex. `https://simul.fintech4esg.com`)
   — pour le CORS.

---

## 7. Le déroulé de déploiement (une fois §6 fourni)

1. `git clone` sous `/home/apps/loader`, `.env` de prod rempli.
2. `docker compose up -d --build` → `curl 127.0.0.1:8003/health` = 200.
3. vhost nginx : `proxy_pass 127.0.0.1:8003` (+ `certbot` si Option B),
   `nginx -t` **avant** `reload` (refuse une config cassée).
4. `curl https://<domaine-backend>/health` = 200 public ; `/docs` en ligne.
5. Sonde E1 verte sur les 10 services (depuis le serveur).
6. Login admin → changement du mot de passe initial.
7. **Adoption A-13** des 11 rôles sur l'instance hébergée.
8. DRY_RUN 2000 depuis le serveur (latence réelle).
9. Paliers REAL 1→6, `mongodump` avant chacun.

---

## 8. Pièges de junior déjà neutralisés (ce qui distingue cette conception)

- **Port en conflit** (8000 pris) → attrapé par la recon, corrigé en 8003.
- **CORS absent** → le frontend aurait été bloqué en silence ; ajouté + testé.
- **Réseau en doublon** → on adopte `loader-net` au lieu d'en créer un second.
- **Déploiement en root** → sous `apps`, comme les autres projets.
- **`reload nginx` sur config cassée** → `nginx -t` obligatoire d'abord.
- **Secret JWT éphémère** → rendu obligatoire en prod, documenté.
- **Perte de la mémoire** → volume nommé + `mongodump` avant chaque palier.
- **Secrets dans l'image** → `.dockerignore` liste blanche, structurel.
