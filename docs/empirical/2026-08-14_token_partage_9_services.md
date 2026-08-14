# Preuve empirique — un seul token ROOT vaut pour les 9 services (14/08/2026)

**Nature : lecture seule.** UN login ROOT réussi (INV-USR-19 respecté, aucun
échec), puis des GET authentifiés. Aucune écriture, aucun run. Test exécuté
DEPUIS le conteneur déployé (`loader-loader-1`) sur le serveur.

## La question (doute légitime de Yaniv)

Le Loader s'authentifie UNE fois sur user-service et réutilise le token comme
`Bearer` sur les 9 services (session partagée, `ECART-38`). Mais la plateforme
ACCEPTE-t-elle vraiment un token de user-service sur les autres services, ou
chaque service exige-t-il sa propre authentification ?

## La mesure

```
POST user-service /api/v1/auth/login  (ROOT)     -> 200, access_token obtenu
GET  product-service  /products/    + CE token   -> 200
GET  company-service  /companies/   + CE token   -> 200
GET  depositary-service /depositaries/ + CE token -> 200
```

## Le verdict

**Authentification CENTRALISÉE confirmée.** Un unique JWT ROOT est validé par
tous les services (passerelle commune). Le modèle du Loader — un login, un
token partagé par les 9 clients avec verrou de renouvellement anti-lockout — est
donc VALIDE empiriquement, pas seulement implémenté. Ce que le code suppose
(`base.py`, D-DEP-7), la plateforme le tient.
