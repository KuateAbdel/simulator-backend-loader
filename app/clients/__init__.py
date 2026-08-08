"""Clients HTTP sortants (httpx async, HTTP/2 via APISIX 3.13.0).

Vide a ce stade -- squelette initial. Un client par cible externe, JAMAIS un
client generique unique : les 9 microservices FinZuu portent chacun ses
propres ecarts empiriques (10_component.puml), les fusionner effacerait cette
realite et les garde-fous specifiques qui en decoulent.
"""
