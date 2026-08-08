"""Clients HTTP sortants (httpx async, HTTP/2 via APISIX 3.13.0).

`contracts.py` fige les enums et constantes des contrats FinZuu amont, recopies
depuis les pages Service Anatomy (espace TST) et la Cartographie Faker v1.1.
Toute valeur envoyee a un service FinZuu vient de la — jamais d'un sondage
refait sur le moment.

Les clients eux-memes restent a ecrire. Un client par cible externe, JAMAIS un
client generique unique : les 9 microservices portent chacun ses propres ecarts
empiriques (10_component.puml), les fusionner effacerait cette realite et les
garde-fous specifiques qui en decoulent.
"""
