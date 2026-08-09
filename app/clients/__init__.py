"""Clients HTTP sortants (httpx async, HTTP/2 via APISIX 3.13.0).

`contracts.py` fige les enums et constantes des contrats FinZuu amont, recopies
depuis les pages Service Anatomy (espace TST) et la Cartographie Faker v1.1.
Toute valeur envoyee a un service FinZuu vient de la — jamais d'un sondage
refait sur le moment.

**Les 9 clients sont ecrits** (09/08/2026). Un client par cible externe, JAMAIS
un client generique unique : les 9 microservices portent chacun ses propres
ecarts empiriques (10_component.puml), les fusionner effacerait cette realite et
les garde-fous specifiques qui en decoulent.

    account  ·  client  ·  collect  ·  company  ·  config
    depositary  ·  identity  ·  product  ·  user

Chaque module porte en tete les disciplines mesurees sur SON service, avec la
date de la mesure. Une discipline heritee d'une page Confluence est TOUJOURS
rejouee avant d'etre codee — c'est ainsi que `D-CLI-3` s'est revelee caduque et
que `D-CLI-8` a ete decouverte.
"""
