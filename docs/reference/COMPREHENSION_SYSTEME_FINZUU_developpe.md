# Compréhension du système FinZuu — développée

> **Ce document accompagne `COMPREHENSION_SYSTEME_FINZUU.md`.** Le premier est la
> référence structurée (tableaux, verdicts). Celui-ci est la **pensée développée**
> — les raisonnements complets, les analogies, les « pourquoi » tels qu'ils ont
> été construits le 10 août 2026 en lisant la documentation et en interrogeant le
> système. Rien n'est condensé ici : c'est la matière brute de la compréhension.

---

## I. Ce qu'est FinZuu, vraiment — au-delà de la définition

Le CDC dit « plateforme FinTech-as-a-Service ». C'est vrai, mais froid. Ce que
ça veut dire concrètement, c'est ceci.

Il existe en Afrique subsaharienne des millions de gens qui n'ont pas de compte
en banque. Pas parce qu'ils n'ont pas d'argent — parce que la banque n'est pas
venue à eux. Il n'y a pas d'agence dans leur village, pas de distributeur, et
souvent pas d'internet sur leur téléphone. Ils épargnent en liquide, sous le
matelas, ou confient leur argent à un collecteur de quartier qui passe chaque
matin. C'est le système de la **tontine** et du **collecteur ambulant**,
vieux comme le commerce.

FinZuu numérise **exactement ce système-là**, sans le détruire. Le collecteur
existe toujours — mais maintenant il a un téléphone, il enregistre la collecte,
et le client reçoit un SMS. L'agriculteur qui n'a pas de smartphone compose
`*144#` et consulte son épargne **sans internet**, sur un téléphone à touches.

Voilà pourquoi tout dans ce système est pensé pour la **basse connectivité** et
le **terrain** : l'USSD, le réseau d'agents, la collecte physique. Ce n'est pas
une banque en ligne de plus. C'est l'inclusion financière de ceux que les
banques ont laissés dehors.

**Et « marque blanche multi-tenant » veut dire :** FinZuu ne vend pas ses
services aux clients finaux. Il vend **la plateforme** à des institutions —
Baobab Finance en Côte d'Ivoire, SoliMFI au Cameroun, GreenPay au Ghana. Chacune
loue le logiciel, met son logo dessus, et l'utilise pour ses propres clients.
Trois banques différentes, une seule infrastructure, des données étanches. C'est
un immeuble avec plusieurs locataires qui ne se voient pas.

**Ce détail — le multi-tenant — explique la moitié des choix techniques du
système**, y compris les menus (on y reviendra). Gardez-le en tête.

---

## II. Les 5 acteurs — et pourquoi ROOT n'est pas comme les autres

Il y a cinq types d'utilisateurs dans le système. Quatre d'entre eux
fonctionnent de la même façon : ils reçoivent des permissions, et le serveur
vérifie ces permissions avant de les laisser agir. Le cinquième, ROOT, est
différent — et cette différence n'est pas un détail, c'est structurel.

**STAFF, COMPANY, CUSTOMER, GUEST** sont des utilisateurs *bornés*. Chacun a un
groupe, le groupe a des permissions, et à chaque action le serveur demande :
« cet utilisateur porte-t-il la permission `X` ? ». S'il ne l'a pas, il est
refusé. C'est le RBAC classique.

**ROOT est un *bypass*.** Le serveur **ne vérifie pas** ses permissions. ROOT
peut tout faire, non pas parce qu'il porte toutes les permissions, mais parce
que le système ne pose même pas la question pour lui.

Je ne le déduis pas de la doc — je l'ai **mesuré**. Le groupe `ROOT` en base ne
porte **pas** la permission `COLLECT_WRITE`. Et pourtant ROOT peut collecter.
Un STAFF sans cette permission est bloqué net ; ROOT sans cette permission passe
quand même. **La permission qui manque à ROOT ne l'arrête pas, parce qu'on ne la
lui demande jamais.** C'est la preuve technique parfaite qu'il est d'une autre
nature.

Pensez au directeur général d'une banque. Il n'a pas de « badge d'accès au
coffre » — il n'en a pas besoin, c'est le directeur, toutes les portes s'ouvrent
pour lui par principe. Un caissier, lui, a un badge précis qui ouvre précisément
sa caisse et rien d'autre. ROOT est le directeur. Les autres ont des badges.

**Pourquoi ça compte pour nous :** le Loader écrit **toujours en ROOT**. C'est
notre discipline `D-DEP-7`. Et maintenant on comprend *pourquoi* c'est le bon
choix : ROOT est le seul acteur qui peut peupler tout l'écosystème sans jamais se
heurter à un refus de permission. Si le Loader opérait en STAFF, il serait bloqué
dès qu'il toucherait une fonction que ce STAFF n'a pas — exactement le piège du
bug `FRA-48`, où un STAFF mal outillé recevait 403 partout. ROOT n'a pas ce
problème : il est hors matrice.

---

## III. Les 4 niveaux d'accès — l'erreur à ne jamais commettre

C'est le cœur de tout, et c'est aussi là qu'on s'embrouille le plus facilement.
Il y a **quatre** concepts différents dans le contrôle d'accès de FinZuu, et ils
se ressemblent assez pour qu'on les confonde. Séparons-les une fois pour toutes.

**Niveau 1 — le TYPE (il y en a 5).** C'est la grande catégorie : ROOT, STAFF,
COMPANY, CUSTOMER, GUEST. Le type ne dit pas ce que tu fais précisément — il dit
**dans quel monde tu es**. Es-tu du siège FinZuu (STAFF) ? Du personnel d'une
institution cliente (COMPANY) ? Un client final (CUSTOMER) ? Le type **borne**
ce que tu peux recevoir. Un CUSTOMER ne recevra jamais le droit d'administrer le
système — son type le lui interdit d'entrée.

**Niveau 2 — le RÔLE, ou GROUPE (il y en a 12 chez nous).** C'est un **paquet de
permissions** avec un nom métier : Comptable, Agent, Kiosque, Compliance… Le rôle
n'est pas une permission unique, c'est un **ensemble** de permissions qui vont
ensemble parce qu'elles forment un métier. Le rôle « Comptable » regroupe toutes
les permissions liées aux comptes. On crée les rôles **une seule fois**, et
ensuite on y rattache des gens.

**Niveau 3 — la PERMISSION (il y en a 40).** C'est l'habilitation atomique :
`COLLECT_COLLECT_WRITE`, `USER_USER_READ`, `ACCOUNT_TRANSACTION_WRITE`… **C'est
CECI que le serveur vérifie réellement.** Pas le type, pas le nom du rôle — la
permission. Quand tu tentes une collecte, le serveur ne demande pas « es-tu de
type COMPANY ? », il demande « portes-tu `COLLECT_WRITE` ? ».

**Niveau 4 — le MENU.** On y vient en détail plus loin. En un mot : c'est ce que
tu **vois** à l'écran, filtré par tes permissions.

La chaîne, dans l'ordre :

```
Le TYPE borne ce que tu peux recevoir.
Le RÔLE regroupe les permissions d'un métier.
La PERMISSION autorise l'action (c'est elle que le serveur vérifie).
Le MENU montre l'écran correspondant.
```

**La phrase à retenir :** *le pouvoir d'agir ne vient jamais du type seul — il
vient de la permission portée.* Celui qui peut collecter, c'est celui qui porte
`COLLECT_WRITE`. Ce peut être un Agent (COMPANY), un Kiosque (COMPANY), ou même
le client lui-même (CUSTOMER, pour son propre argent). Le type dit *jusqu'où* on
peut aller ; la permission dit *ce qu'on fait vraiment*.

Cette distinction n'est pas académique. Elle a produit une vraie correction dans
notre code — voir la section suivante.

---

## IV. Nos 12 rôles — et l'erreur que la doc m'a fait corriger

Nos 12 rôles viennent de la « Stratégie Seed v2.0 », une page Confluence. Mais
cette page dit une chose importante : *« le mapping des 12 rôles vers les 5
UserType n'est pas encore matérialisé »*. Autrement dit — **personne n'avait
décidé quel rôle correspond à quel type.** C'était un trou.

J'ai comblé ce trou dans la décision `D-09`, en juin, en décidant. Et j'ai
décidé **mal**. J'avais mis 9 des 12 rôles en type STAFF.

Pourquoi c'était faux ? Parce que STAFF, dans FinZuu, désigne **le siège de
FinZuu lui-même** — l'équipe qui développe et administre la plateforme. Or le
Loader ne génère pas le siège FinZuu. **Le Loader génère des institutions
clientes** — des IMF, avec leur personnel : des agents, des guichetiers, des
chefs de branche, des comptables d'institution. Ces gens-là ne sont pas du siège
FinZuu. Ils appartiennent à une **institution**. Et le type des gens d'une
institution, c'est **COMPANY**.

Le CDC le dit noir sur blanc : *« il rattache chaque Agent à une Company mère »*.
L'Agent appartient à une Company. Le Manuel de Référence le confirme : *« CO
englobe le Business, l'Agent, le Kiosque, la Secrétaire, le CFO, le Guichetier »*.
Tous ces métiers sont du type COMPANY.

Donc j'ai corrigé. Le bon mapping :

- **ROOT** : Super-Admin (administration de la plateforme). Un seul.
- **STAFF** : Compliance et Employé/IT. Pourquoi ces deux-là seulement ? Parce
  que la validation finale du KYC, l'exploitation, les logs système — ce sont
  des fonctions **exclusives au siège FinZuu** selon la Matrice RBAC. Ces deux
  rôles-là représentent vraiment FinZuu, pas une institution.
- **COMPANY** : les huit autres — Admin, Marketing, Collecte, Comptable, Branche,
  Agent, Marchand, Kiosque. Tout le personnel opérationnel des institutions.
- **CUSTOMER** : le Client.

Et j'ai fait plus que corriger le code — j'ai **resynchronisé la base**. Parce
que les groupes créés le 9 août portaient l'ancien type, et le `GET`-avant-`POST`
ne les aurait jamais corrigés (il réutilise par nom, il aurait gardé l'ancien
type). Il a fallu **supprimer** les 6 rôles mal typés (`DELETE` existe, c'est
prouvé) et les **recréer** avec le bon type. Résultat vérifié : 16 groupes en
base, 12/12 alignés, **zéro doublon**. Pas de « Agent » en double, pas de
résidu — l'ancien supprimé avant le nouveau créé.

**Un point que je tiens à souligner :** cette correction n'a touché **que le
type**. Les permissions n'ont pas bougé. C'est important, parce que le type
(niveau 1) et les permissions (niveau 3) sont deux choses distinctes. Les
permissions par rôle restent un arbitrage ouvert (`A-05`) — une proposition que
Yaniv validera sur pièce. Je n'ai pas mélangé les deux.

---

## V. CUSTOMER contre Client — la confusion qui piège tout le monde

Voici la confusion la plus naturelle du système, et il faut la tuer nettement.

Il y a un **type d'utilisateur** qui s'appelle CUSTOMER. Et il y a une **entité
métier** qui s'appelle Client. Les deux mots veulent dire « client » en
français. Mais **ce ne sont pas la même chose, et ils ne vivent même pas dans le
même service.**

Le **User de type CUSTOMER** vit dans **user-service**. Il répond à la question
*« qui a le droit de se connecter à la plateforme, et avec quel mot de passe ? »*.
Il contient un nom d'utilisateur, un mot de passe, des groupes. C'est un
**identifiant de connexion**.

Le **Client** vit dans **client-service**. Il répond à une question complètement
différente : *« qui a souscrit à un produit d'épargne, et combien possède-t-il ? »*.
Il contient un numéro de téléphone (msisdn), une catégorie, une liste de produits,
un compte. C'est une **relation commerciale** — le dossier client.

Ce sont **deux enregistrements séparés, dans deux bases de données différentes.**

Une même personne réelle peut correspondre à **trois objets** :
- une **Identity** (identity-service) — son KYC, sa pièce d'identité ;
- une **Client subscription** (client-service) — son épargne ;
- et *éventuellement* un **User CUSTOMER** (user-service) — pour se connecter à
  l'App.

« Éventuellement », parce qu'un client qui n'utilise que l'USSD n'a même pas
besoin d'un compte user classique — il est reconnu par son **numéro de
téléphone**. Le MSISDN est sa clé.

**Ce que ça change pour compter :** quand le CDC dit « 2 000 clients », ce sont
2 000 **Client subscriptions**, pas 2 000 comptes de connexion. Le Loader crée
côté user-service environ **111 comptes** (le staff et les admins), pas 2 111.
Les 2 000 clients sont des dossiers dans client-service, avec leur identité dans
identity-service. Confondre les deux, c'est se tromper d'un facteur 20 sur le
volume.

**Et sur les droits :** le groupe CUSTOMER porte, je l'ai mesuré, la permission
`COLLECT_WRITE`. Donc un client **peut** faire sa propre collecte — épargner,
retirer — depuis son mobile. Ce qu'il ne peut pas faire, c'est agir sur le compte
d'**un autre** (ça, c'est le rôle du collecteur, type COMPANY), ni **confirmer**
un dépôt (ça, c'est le siège, STAFF). Le client agit **pour lui-même, jamais pour
autrui**. C'est cohérent avec la vraie vie : on ne s'auto-crédite pas l'argent
d'un voisin.

---

## VI. Les menus — le concept que j'avais sous-estimé

Au début, je croyais qu'un menu, c'était juste « une entrée de navigation ». Un
bouton dans une barre latérale. C'est vrai en surface, mais c'est passer à côté
du purpose. En réalité, les menus résolvent un problème profond, et pour le
comprendre il faut revenir au multi-tenant.

**Premier niveau de compréhension — le menu contrôle ce qu'on peut VOIR
EXISTER.** Il y a une différence entre « tu n'as pas le droit de faire ça » et
« tu ne sais même pas que ça existe ». La permission fait la première ; le menu
fait la seconde. Un Agent de terrain ne voit pas le menu « Définir les taux
d'intérêt ». Non seulement il ne peut pas y toucher — il **ignore que cette
fonction existe**. Son écran ne la contient pas. C'est à la fois de la sécurité
(on ne tente pas ce qu'on ne voit pas) et de la simplicité (son écran ne contient
que ce qui le concerne — précieux pour un utilisateur peu à l'aise avec le
numérique).

L'image : la permission est **la clé qui ouvre une porte**. Le menu est **le fait
de voir qu'il y a une porte**. On peut te cacher une porte sans même avoir besoin
de la verrouiller.

**Deuxième niveau — et c'est LE purpose fondamental : les menus sont le cœur
technique de la marque blanche.**

Posez-vous la question : pourquoi stocker les menus **dans la base de données**,
au lieu de les écrire en dur dans le code de l'interface ?

Parce que FinZuu est multi-tenant. Une **banque** n'a pas besoin des mêmes écrans
qu'une **IMF de collecte de déchets plastiques**. Si les menus étaient codés en
dur dans le frontend, il faudrait un logiciel différent par client — ce qui
détruit tout l'intérêt de la marque blanche. En stockant les menus en base,
**chaque tenant configure ses propres écrans**, sur le même logiciel, sans qu'un
développeur ne recompile quoi que ce soit. Baobab active les menus « crédit »,
GreenPay active les menus « collecte de déchets », et c'est **la même
application** qui se dessine différemment.

C'est ce que le Core Engine appelle *« Dynamic UI Rendering — Permission-Based
UI »*. L'interface n'est pas figée : elle **se rend dynamiquement** selon les
menus du groupe de l'utilisateur, et ces menus sont filtrés par les permissions.

**Troisième niveau — le Zero Trust.** Le frontend ne décide **jamais** seul ce
qu'il affiche. Il **demande au serveur** : « quels menus pour cet utilisateur ? ».
Le serveur répond avec la liste autorisée. Pourquoi ? Parce qu'un frontend, ça se
pirate. Si c'était le navigateur qui décidait quoi montrer, un attaquant pourrait
forcer l'affichage d'écrans interdits. En laissant le **backend** décider, on
garantit qu'un frontend compromis ne peut rien révéler qu'il ne devrait — c'est
la sécurité en profondeur.

**Quatrième niveau — la traçabilité.** Le journal d'audit (`log_user`) enregistre
*« le menu mis en cause »* pour chaque action. Donc quand on audite qui a fait
quoi, on sait aussi **depuis quel écran** l'action est partie. Exigence de
conformité anti-blanchiment (AML).

**L'analogie complète :** une banque physique est faite de portes. La
**permission**, c'est la clé qui ouvre une porte donnée. Le **menu**, c'est le
fait de voir la porte dans le couloir. Un client voit le guichet « dépôt-retrait ».
Un employé voit la porte « back-office ». Le directeur voit le coffre. **Même
bâtiment, mais chacun ne voit que les portes qui le concernent.** Le menu, c'est
le plan du bâtiment tel qu'on te le montre selon qui tu es — et dans un immeuble
multi-locataires, chaque locataire dessine son propre plan.

**Ce que ça change pour le Loader :** rien, et c'est doctrinalement juste. Les
menus sont de la **configuration d'interface** — ils décrivent le BackOffice
(développé par Zidane), pas la donnée métier. Le Loader peuple **qui existe et
combien il possède** ; il ne configure pas **comment on le montre à l'écran**.
Notre mandat (`ENF-16`) est un orchestrateur de données, pas un configurateur
d'UI. Mais comprendre les menus change une chose dans notre esprit : nos 12 rôles
ne servent pas qu'à autoriser des actions — ils décident aussi **ce que chaque
personne verra à l'écran**. Quand un Comptable et un Agent se connecteront à la
démo, le BackOffice leur montrera deux interfaces différentes, **grâce aux rôles
qu'on a créés**. C'est une raison de plus pour que le mapping type/rôle soit
juste.

---

## VII. La collecte — comment ça marche vraiment

La collecte, c'est le cœur métier de la microfinance de proximité. Et j'avais une
vision trop simple au début — « le dépositaire fait la collecte ». La
documentation m'a montré que c'est plus riche : **c'est un flux à deux temps,
avec trois acteurs.**

**Les trois natures de collecte**, selon le type de produit souscrit :
- **CASH** — de l'épargne classique en argent. On suit un montant en devise.
- **CASH_DAT** — de l'épargne à terme, bloquée pour une durée fixée. Montant +
  date de fin.
- **PRODUCT** — de la collecte d'**objets physiques** : cacao, plastique,
  ferraille, récoltes. On ne suit pas de l'argent mais une **quantité** avec une
  unité (kilogramme ou litre). C'est le versant « économie circulaire » du
  système — un collecteur de déchets plastiques qui crédite le client au poids.

**Le flux à deux temps :**

Premier temps, l'**initiation**. C'est l'Agent (type COMPANY) qui, sur le
terrain, reçoit le cash du client et enregistre la collecte. Ou bien c'est le
client lui-même (CUSTOMER), depuis son mobile, qui initie son épargne. Dans les
deux cas, à ce stade, l'argent est **enregistré mais pas encore confirmé**.

Deuxième temps, la **validation**. Le Manuel est explicite : *« la validation
finale d'une collecte terrain se fait par le Staff au niveau du Dashboard, après
remise du cash physique par l'agent »*. Autrement dit : l'agent a collecté du
liquide toute la journée sur le terrain ; le soir, il remet ce liquide au siège ;
et c'est **le Staff** qui, ayant l'argent physique en main, **confirme** les
collectes dans le système.

**Ce double temps n'est pas une lourdeur — c'est du contrôle.** L'agent qui
collecte n'est pas celui qui valide. C'est la séparation des fonctions, la base
de tout contrôle financier : celui qui touche l'argent ne peut pas
l'auto-valider. Et ça correspond **exactement** à ce qu'on avait mesuré sans le
comprendre : `ANO-ACC-STATUS-05`, où un dépôt reste `PENDING`. Ce n'était pas un
bug — c'est le flux métier. Le dépôt est `PENDING` **parce qu'il attend la
confirmation du siège**.

**Les préconditions**, mesurées une par une : le client doit exister, le produit
doit exister, et le dépositaire doit être **souscrit à ce produit précis** — pas
juste exister, mais avoir souscrit à exactement ce produit. C'est pour ça que le
Loader doit créer les produits **avant** les dépositaires, et les dépositaires
**avant** les collectes. L'ordre n'est pas un choix, c'est une contrainte de
dépendance.

---

## VIII. La règle d'or — pourquoi on ne casse pas notre géographie

Tout au long de cet audit, une tentation était présente : « la doc ne parle pas
de régions ni de quartiers, donc peut-être qu'on devrait simplifier notre
géographie pour coller à la doc ». **C'est exactement ce qu'il ne faut pas
faire**, et la doctrine le dit depuis le début.

Il y a deux plans qu'il faut traiter différemment.

**Le TRANSPORT** — les enums, les types, les noms de champs qu'on envoie au
serveur. Là, on est **conformiste**. On suit leur contrat à la lettre. Si le
serveur attend `UserType.COMPANY`, on envoie exactement ça. C'est pour ça que
corriger l'Agent de STAFF à COMPANY était juste : c'est du transport, on doit
être fidèle à leur contrat. Et j'ai vérifié — nos **enums sont alignés à 100 %** :
les 5 types, les 7 types de compagnie, les 8 types de compte, les policies, les
canaux. Tout.

**Le MODÈLE** — notre représentation interne du monde. Là, on est
**anti-corruption**. On garde **notre** modèle, plus riche que le leur, et on ne
le dégrade pas pour coller à un serveur plus pauvre. Notre géographie fine
(régions, villes, quartiers avec leur `zone_type`), notre arbre à quatre niveaux,
notre journal d'intention — ce sont des choses que le serveur ne sait même pas
exprimer, et c'est **notre valeur**.

Le fait que la doc Confluence ne mentionne pas nos régions et quartiers **ne les
rend pas faux**. Ça les rend **plus riches**. Le CDC lui-même confirme d'ailleurs
notre arbre (« Agent rattaché à une Company mère », « arbre géographique à cinq
niveaux ») — donc notre modèle n'est même pas une invention, c'est le leur, en
plus détaillé.

**La phrase qui gouverne tout, et qui est de Yaniv, pas d'un livre :** *« on ne
détruit pas notre conception pour s'aligner sur le service du système ».* C'est
le motif Anti-Corruption Layer d'Eric Evans, énoncé par quelqu'un qui n'avait pas
besoin du nom pour avoir l'idée.

Donc : **on aligne les contrats, on garde notre richesse.** Corriger un type de
rôle ne touche pas la géographie — le type est du transport, la géographie est du
modèle. Les deux corrections vivent sur deux plans qui ne se croisent pas.

---

## IX. Ce que tout cet audit a établi, en une prise de recul

Trois jours de mesures empiriques nous avaient donné le **comment** — les 65
disciplines, chacune adossée à un comportement serveur mesuré. Ce que la lecture
de la documentation nous a donné aujourd'hui, c'est le **pourquoi** — la raison
d'être de chaque service, le sens métier de chaque acteur, la logique du contrôle
d'accès.

Et le croisement des deux a produit une conclusion nette : **notre conception est
juste, et là où elle divergeait de la doc, c'est presque toujours la doc qui
confirmait notre richesse — sauf un point, le type de l'Agent, où c'est nous qui
avions tort, et qu'on a corrigé.**

Rien de fondamental n'est cassé. Les enums sont fidèles. La géographie est notre
force et le CDC la valide. L'arbre est le modèle métier réel. Le mapping des
rôles est maintenant aligné. Et surtout — on comprend désormais **pourquoi**
chaque chose est comme elle est, pas seulement **comment** elle se comporte.

C'est la différence entre un technicien qui sait faire marcher un système, et un
ingénieur qui sait pourquoi il est construit ainsi. On est passé du premier au
second aujourd'hui.

---

*Développé le 10 août 2026. Ce document capture le raisonnement dans sa forme
longue ; la version structurée est dans `COMPREHENSION_SYSTEME_FINZUU.md`.*
