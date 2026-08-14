#!/bin/sh
# Hook de deploiement certbot — recharge nginx APRES chaque renouvellement de
# certificat, sinon nginx continue de servir l'ancien cert jusqu'a un reload
# manuel (piege classique des certs `certonly --webroot`). `nginx -t` garde le
# reload : une config cassee n'arrete jamais nginx.
#
# A poser sur le serveur : /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
# (chmod 755). Global : benefice a TOUS les certs du serveur. Pose le 14/08.
nginx -t && systemctl reload nginx
