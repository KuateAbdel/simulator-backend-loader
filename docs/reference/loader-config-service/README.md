# loader-config-service

Loader discipline senior pour peupler `config-service` (FinZuu) a partir
des 3 CSV de reference. Ordre topologique strict :
**Currencies → Telcos → Countries**.

## Arborescence (script et CSV DOIVENT rester dans la meme structure)

```
loader-config-service/
├── loader_config_service.py   <- le script
├── requirements.txt
├── .env.example                <- a copier en .env
├── data/
│   ├── currencies.csv
│   ├── telcos.csv
│   └── countries.csv
├── state/                      <- genere automatiquement (UUID captures)
└── logs/                       <- genere automatiquement (SIEM local, 1 fichier par run)
```

Le script localise `data/` relativement a sa propre position
(`Path(__file__).parent / "data"`), donc tu peux deplacer tout le dossier
`loader-config-service/` n'importe ou sur ta machine — tant que la
structure interne est preservee, ca marche. Tu peux aussi pointer ailleurs
avec `--data-dir /chemin/vers/un/autre/dossier`.

## Installation

```bash
cd loader-config-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# éditer .env avec le vrai mot de passe Root
export $(cat .env | xargs)
```

## Usage

```bash
# 1. Dry-run obligatoire d'abord -- affiche ce qui serait fait, n'ecrit rien
python3 loader_config_service.py

# 2. Une fois valide, execution reelle
python3 loader_config_service.py --execute
```

Le script :
1. Se logue en Root sur `user-service` (jamais de token en dur ou recycle)
2. Sonde `config-service` avant de commencer -- s'arrete proprement et
   lisiblement si le 403 documente (bug FRA-48 / ecart empirique du
   27/07/2026) est toujours present
3. Charge Currencies, puis Telcos, puis Countries -- dans cet ordre
   uniquement, jamais autrement (Country depend des UUID des deux autres)
4. Est idempotent : relancer le script ne duplique rien (GET avant chaque
   POST, skip si deja present)
5. Ecrit un rapport final + un log JSONL horodate dans `logs/` + les UUID
   captures dans `state/`

## Anomalies serveur connues et neutralisees par ce script

Voir les commentaires en tete de `loader_config_service.py` -- chaque
anomalie documentee (Confluence "Anomalies config-service") y est listee
avec la mitigation exacte appliquee cote client.
