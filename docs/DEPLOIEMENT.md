# Déploiement — simul.fintech4esg.com, depuis GitHub, chirurgical

> Décision C-0 (13/08) : **héberger avant de charger**. La recon passive du
> 14/08 l'a confirmée par la mesure : 4–6 s par `/health` depuis la machine
> de dev, DNS instable — ENF-01 est intenable d'ici. Tout run REAL part du
> serveur.

## 0. LE SERVEUR EST PARTAGÉ — reconnaissance SSH du 14/08

`152.53.118.110` (Netcup, Ubuntu 24.04 ARM64, 10 vCPU, 16 Go, 460 Go libres)
héberge **déjà 3 projets critiques** : ERPNext CRM, Nextcloud Talk/Collabora,
Newsletter (Zidane). **On ne touche à RIEN de tout ça.** Faits qui commandent
notre déploiement :

- **nginx est sur le HOST (systemd), pas dockerisé** — il est le seul pont
  Internet→conteneurs, `enabled` au boot. Notre vhost `simul.conf` **existe
  déjà** (préparé par Yaniv : renvoie 503 + cert Let's Encrypt valide au
  18/10). On ne le CRÉE pas, on modifie juste son `location /`.
- **Le port 8000 est PRIS** (`finzuu-talk-recording`). Le Loader prend **8003**
  (libre) — déjà corrigé dans `docker-compose.yml`.
- **Réseau `loader-net` déjà pré-créé** (vide, prêt — préparé par Yaniv) : le
  compose l'adopte en `external`, pas de doublon. Chaque app a son réseau isolé.
- **User de déploiement = `apps`** (groupes `sudo`+`docker`), sous
  `/home/apps/` — jamais root pour une app sur un serveur partagé. Les autres
  projets vivent sous `/home/apps/{erpnext-production,finzuu,newsletter}`.
- Les secrets des autres services (ERPNext, Newsletter, TURN…) ont été **vus**
  pendant la recon : **hors de notre périmètre, jamais copiés, jamais dans ce
  dépôt.**

## 1. La chaîne, en une phrase

`git push main` → **CI** (ruff + mypy strict + 948 tests contre un vrai
MongoDB) → si VERTE seulement → **CD** : SSH vers le serveur (hôte vérifié
par empreinte), `git merge --ff-only`, `docker compose up -d --build`
(build **natif ARM64** sur le serveur), et le job n'est réussi que si
`/health` répond 200 — la preuve, jamais la déduction.

## 2. Les pièces (dans ce dépôt)

| Fichier | Rôle |
|---|---|
| `Dockerfile` | image uv/py3.12 multi-arch, non-root, `docs/reference/` embarqué (chemins relatifs du code), HEALTHCHECK sur `/health` |
| `.dockerignore` | **liste blanche** — un secret ne PEUT PAS entrer dans l'image |
| `docker-compose.yml` | loader + mongo ; volume nommé (la MÉMOIRE du Loader) ; mongo sans port publié ; loader sur `127.0.0.1:8003` seulement (8000 pris — recon), réseau `loader-net` externe ; le nginx du HOST expose le 443 |
| `.github/workflows/ci.yml` | les portes du protocole §6, sur chaque push/PR |
| `.github/workflows/deploy.yml` | le déploiement, uniquement après CI verte de main |

## 3. CE QU'IL FAUT FAIRE UNE FOIS (Yaniv) — 15 minutes

### a) La clé SSH de déploiement (dédiée, jamais ta clé personnelle)
```bash
ssh-keygen -t ed25519 -C "deploy-loader-finzuu" -f deploy_key -N ""
ssh-copy-id -i deploy_key.pub <user>@152.53.118.110   # ou colle deploy_key.pub dans ~/.ssh/authorized_keys
ssh-keyscan -t ed25519 152.53.118.110                  # -> la ligne pour DEPLOY_KNOWN_HOSTS
```

### b) Les 4 secrets GitHub (Settings → Secrets and variables → Actions)
| Secret | Valeur |
|---|---|
| `DEPLOY_HOST` | `152.53.118.110` |
| `DEPLOY_USER` | l'utilisateur SSH |
| `DEPLOY_SSH_KEY` | le contenu de `deploy_key` (la privée) |
| `DEPLOY_KNOWN_HOSTS` | la ligne `ssh-keyscan` ci-dessus |

Variable optionnelle : `DEPLOY_PATH` (défaut `/home/apps/loader`).

### c) Préparer le serveur (une fois) — user `apps`, docker déjà présent
```bash
ssh apps@152.53.118.110          # docker 29.7 + compose v5.4 déjà installés
git clone https://github.com/KuateAbdel/simulator-backend-loader.git /home/apps/loader
cd /home/apps/loader && cp .env.example .env && nano .env   # voir §4
docker compose up -d --build && curl -fsS http://127.0.0.1:8003/health
```
Le réseau `loader-net` existe déjà (préparé) — le compose l'adopte.

### c-bis) Créer le vhost du BACKEND `simul.api.fintech4esg.com` (root)
**Décision Option B (14/08)** : le backend est sur `simul.api.fintech4esg.com`.
On **ne touche PAS** à `simul.conf` (c'est le frontend de Zidane). On **crée**
un vhost séparé + son certificat (le DNS `simul.api` résout déjà).

1. Obtenir le certificat (nginx tourne, certbot en mode webroot) :
```bash
certbot certonly --webroot -w /var/www/certbot -d simul.api.fintech4esg.com
```
2. Poser le vhost (le fichier est fourni : `deploy/nginx/simul-api.conf`) :
```bash
cp /home/apps/loader/deploy/nginx/simul-api.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/simul-api.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx      # -t REFUSE une config cassée
curl -fsS https://simul.api.fintech4esg.com/health   # 200 public
```
Swagger en ligne pour Zidane : `https://simul.api.fintech4esg.com/docs`.

### d) La fiche du dépôt (gh non authentifié sur la machine de dev)
Tape dans la session : `! gh auth login` — puis je pose description, topics
et protection de branche. Ou à la main :
```bash
gh repo edit KuateAbdel/simulator-backend-loader \
  --description "Loader FinZuu — backend de pilotage : peuple la plateforme (2000 clients, 9 services) avec traçabilité totale, réconciliation et recette CR-01→CR-12" \
  --add-topic fastapi --add-topic mongodb --add-topic fintech --add-topic data-loader --add-topic microfinance
```

## 4. Le `.env` de PRODUCTION — ce qui change par rapport au dev

| Variable | Règle en production |
|---|---|
| `ADMIN_JWT_SECRET` | **OBLIGATOIRE** (sinon secret éphémère : toutes les sessions meurent à chaque redéploiement) — `openssl rand -hex 32` |
| `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD_INITIAL` | le compte bootstrap ; le mot de passe initial est à changer à la 1ʳᵉ connexion (US-A2, forcé) |
| `MONGODB_URI` | rien à faire — compose l'écrase vers `mongodb://mongo:27017` |
| `FAKER_API_KEY`, `ROOT_USERNAME/PASSWORD` | comme en dev — jamais dans l'écran, jamais dans Git |
| bases des 9 services | **TEST uniquement** (ENF-16/R-06) — les défauts du code sont déjà les bons |

## 5. La mémoire du Loader — sauvegarde AVANT chaque palier REAL

```bash
docker compose exec mongo mongodump --archive | gzip > loader_$(date -u +%Y%m%dT%H%M%SZ).archive.gz
```
Le volume `loader_mongo_data` porte le registre Faker, l'arbre, le journal,
la configuration : le perdre, c'est perdre la preuve CR-03 et la purge.

## 6. Rollback

Un déploiement raté ne s'efface pas, il se **revert** :
```bash
git revert <commit> && git push   # la CI re-passe, le CD redéploie l'état sain
```
Jamais de `git reset --force` sur main — l'historique est append-only, comme
nos runs.

## 7. Après le premier déploiement — l'ordre des opérations

1. `/health` 200 via le vhost → sonde E1 verte sur les 10 services.
2. Login admin, changement du mot de passe initial.
3. **Adoption A-13** : GET inventaire groupes → les 11 rôles (étrangers) →
   POST `/admin/inventaire/groupes/adoption` — ils redeviennent nôtres SUR
   L'INSTANCE HÉBERGÉE (le registre vit dans la Mongo du serveur).
4. DRY_RUN 2000 **depuis le serveur** (latence réelle mesurée).
5. Paliers REAL 1→6, sauvegarde §5 avant chacun.
