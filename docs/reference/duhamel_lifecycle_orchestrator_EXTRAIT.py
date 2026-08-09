"""
docs/reference/duhamel_lifecycle_orchestrator_EXTRAIT.py
========================================================
EXTRAIT DE REFERENCE — code source du referent loan-simulation (Duhamel).

**Ce fichier n'est PAS execute.** Il est la preuve documentaire qui ferme
l'arbitrage `A-06`. Il ne doit jamais etre importe par `app/`.

PROVENANCE : `lifecycle_orchestrator.py` du paquet `ready_scoring/`, transmis
par Yaniv le 9 aout 2026. Jusqu'a cette date, seul le README etait disponible,
et **aucune des 4 fonctions nommees par `EF-76` n'y apparaissait** — d'ou
l'arbitrage `A-06`, qui bloquait les etapes 6 et 7.

CE QUE LE LOADER REPREND — la methodologie, jamais le transport
---------------------------------------------------------------
`ENF-16` interdit explicitement toute dependance a un cluster Kafka, et la
Stack Technique fait du Loader un orchestrateur HTTP pur. Le script original
est un consommateur Kafka de bout en bout : `Consumer`, `Producer`,
`AdminClient`, calibration par timestamps de topic, decouverte automatique de
topics. **Rien de tout cela n'est repris.**

Sont repris ici, verbatim :

  1. Les 4 fonctions de conversion temporelle nommees par `EF-76`
  2. `_adjust_weights` — le coeur intellectuel : 9 variables client -> poids
  3. `_sample_profile` — tirage pondere
  4. `_loan_terms` — matching produit x categorie x segment, avec ses replis

Sont ecartes, avec leur motif :

  Machinerie Kafka complete        `ENF-16` l'interdit
  `calibrate_input_topic_pacing`   depend des timestamps Kafka
  `_check_live`, `_resolve_topics` depend du cluster
  `par_dpd_tracking`               PAR/DPD releve de ReadyScore, hors perimetre
                                   Loader (corrections 9-12 du CDC v1.2)
  `Producer.produce_command`       remplace par des ecritures HTTP FinZuu

CE QUI MANQUE ENCORE — a dire clairement
-----------------------------------------
`built_in_behaviors_v1()["profiles"]` est **importe** par le script, pas
defini dedans. Les 4 profils sont donc **nommes** mais leur FORME — ce que
chacun fait jour apres jour — reste absente. Idem pour `build_timed_actions`,
`expand_actions_daily` et `repay_amount_for_action`.

En revanche, les **poids** sont bien la, en valeurs par defaut du script :
`0.50 / 0.25 / 0.13 / 0.12` — exactement les « poids empiriques 50/25/13/12 »
d'`EF-67`, deja figes dans `app/core/cdc.py`. La concordance est confirmee.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

# --------------------------------------------------------------------------
# 1. Les 4 fonctions de conversion temporelle — EF-76, exigence « M »
#    Reprises VERBATIM. Ce sont ces noms exacts que l'exigence cite.
# --------------------------------------------------------------------------

PROFILE_KEYS = (
    "pay_before_due",
    "partial_then_full_dpd10",
    "partial_then_never_finish",
    "never_pays",
)


def _wall_from_sim_day(
    anchor: datetime | None,
    sim_day: float | None,
    seconds_per_day: float,
) -> str | None:
    if anchor is None or sim_day is None or seconds_per_day <= 0:
        return None
    return (
        (anchor + timedelta(seconds=sim_day * seconds_per_day))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%d %H:%M UTC")
    )


def _current_sim_day(anchor: datetime, seconds_per_day: float) -> float:
    if seconds_per_day <= 0:
        return 0.0
    return (datetime.now(timezone.utc) - anchor).total_seconds() / seconds_per_day


def _wall_time_for_sim_day(anchor: datetime, sim_day: float, seconds_per_day: float) -> datetime:
    return anchor + timedelta(seconds=sim_day * seconds_per_day)


def _scoring_date_to_sim_day(scoring_date: str, sim_start: date) -> float | None:
    try:
        d = date.fromisoformat(str(scoring_date)[:10])
    except ValueError:
        return None
    return float((d - sim_start).days)


# --------------------------------------------------------------------------
# 2. Le coeur intellectuel — 9 variables client vers les poids des 4 profils
#    C'est ce qui rend le comportement credible plutot qu'aleatoire.
# --------------------------------------------------------------------------


def _adjust_weights(base: dict[str, float], ctx: dict[str, Any]) -> dict[str, float]:
    w = {k: max(0.0, float(base.get(k, 0.0))) for k in PROFILE_KEYS}
    sd = ctx.get("scoring_date")
    scoring_year = int(str(sd)[:4]) if sd else None
    birth = ctx.get("birth_date")
    birth_year = None
    if birth:
        m = re.match(r"^(\d{4})", str(birth).strip())
        if m:
            birth_year = int(m.group(1))
    age = (scoring_year - birth_year) if (scoring_year and birth_year) else None

    g = str(ctx.get("gender") or "").strip().lower()
    if g in ("f", "female", "femme", "woman", "w"):
        w["pay_before_due"] *= 1.22
        w["partial_then_full_dpd10"] *= 1.10
        w["partial_then_never_finish"] *= 0.88
        w["never_pays"] *= 0.72
    elif g in ("m", "male", "homme", "man"):
        w["pay_before_due"] *= 0.94
        w["never_pays"] *= 1.08

    if age is not None:
        if age < 22:
            w["partial_then_never_finish"] *= 1.15
            w["never_pays"] *= 1.12
            w["pay_before_due"] *= 0.92
        elif age < 35:
            w["pay_before_due"] *= 1.08
            w["partial_then_full_dpd10"] *= 1.05
        elif age < 50:
            w["pay_before_due"] *= 1.04
        elif age < 65:
            w["pay_before_due"] *= 1.10
            w["never_pays"] *= 0.85
        else:
            w["pay_before_due"] *= 1.06
            w["partial_then_never_finish"] *= 0.90

    seg = str(ctx.get("segment") or "").lower()
    risk = str(ctx.get("risk_class") or "").upper()
    if "very high" in seg or risk == "A":
        w["pay_before_due"] *= 1.12
        w["never_pays"] *= 0.82
    elif "very low" in seg or risk in ("D", "E"):
        w["never_pays"] *= 1.18
        w["pay_before_due"] *= 0.88

    lb = ctx.get("loan_behavior") or {}
    try:
        ratio = float(lb.get("repayment_ratio") or 0.0)
        max_dpd = int(lb.get("max_dpd") or 0)
    except (TypeError, ValueError):
        ratio, max_dpd = 0.0, 0
    if ratio >= 0.85:
        w["pay_before_due"] *= 1.15
        w["never_pays"] *= 0.75
    elif 0 < ratio < 0.5:
        w["never_pays"] *= 1.10
        w["partial_then_never_finish"] *= 1.08
    if max_dpd >= 30:
        w["never_pays"] *= 1.12
        w["pay_before_due"] *= 0.90

    try:
        mob = float((ctx.get("features") or {}).get("MOB_MONEY_ACCOUNT_AMOUNT") or 0.0)
    except (TypeError, ValueError):
        mob = 0.0
    if mob >= 150_000:
        w["pay_before_due"] *= 1.06
    elif 0 < mob < 20_000:
        w["partial_then_never_finish"] *= 1.05

    total = sum(w.values()) or 1.0
    return {k: w[k] / total for k in PROFILE_KEYS}


def _sample_profile(weights: dict[str, float], rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for name in PROFILE_KEYS:
        acc += weights.get(name, 0.0)
        if r <= acc:
            return name
    return PROFILE_KEYS[-1]


# --------------------------------------------------------------------------
# 3. Matching produit x categorie x segment — avec ses deux replis
#    C'est la logique que `EF-69` et `D-08` decrivent cote Loader.
# --------------------------------------------------------------------------


def _loan_terms(
    catalog: dict[str, dict[str, Any]],
    product: str,
    segment: str,
    customer_category: str | None,
    selected_amount: float,
) -> tuple[str, float, int] | None:
    if not product:
        return None
    cat = (
        "Business"
        if str(customer_category or "").strip().lower() in ("business", "corporate", "corp")
        else "Individual"
    )
    rule = catalog.get(product)
    if rule is None:
        return None

    # REPLI 1 — la categorie du client n'est pas eligible au produit demande :
    # on cherche un autre produit compatible plutot que d'echouer.
    if "Any" not in rule["categories"] and cat not in rule["categories"]:
        for name, alt in catalog.items():
            if "Any" in alt["categories"] or cat in alt["categories"]:
                rule, product = alt, name
                break
        else:
            return None

    # REPLI 2 — le segment n'existe pas dans la grille du produit : ordre de
    # repli fige, du plus central vers les extremes.
    pair = rule["amount_ranges"].get(segment)
    if not pair:
        for seg in ("Medium", "High", "Low", "Very High", "Very Low"):
            pair = rule["amount_ranges"].get(seg)
            if pair:
                break
    if not pair:
        return None

    lo, hi = float(pair[0]), float(pair[1])
    amt = max(lo, min(hi, round(float(selected_amount), 2)))
    return product, amt, int(rule["duration_days"])


# --------------------------------------------------------------------------
# 4. Les poids par defaut — concordance avec EF-67 confirmee
# --------------------------------------------------------------------------

#: Valeurs par defaut du script Duhamel (variables d'environnement
#: PROFILE_WEIGHT_*). Elles correspondent EXACTEMENT aux « poids empiriques
#: 50/25/13/12 » d'EF-67, deja figes dans app/core/cdc.py.
POIDS_PAR_DEFAUT_DUHAMEL = {
    "pay_before_due": 0.50,
    "partial_then_full_dpd10": 0.25,
    "partial_then_never_finish": 0.13,
    "never_pays": 0.12,
}

#: Autres parametres du script, utiles au Loader :
#:   LOAN_CREATE_APPROVAL_RATE = 0.90  — 10 % des APPROVED ne sont pas crees,
#:                                       filtre supplementaire de volumetrie
#:   LOAN_DISBURSEMENT_CAP     = 1e9   — plafond global de decaissement
#:   SECONDS_PER_DAY           = 226.49 — repli quand la calibration echoue
LOAN_CREATE_APPROVAL_RATE_DEFAUT = 0.90
LOAN_DISBURSEMENT_CAP_DEFAUT = 1_000_000_000.0
SECONDS_PER_DAY_REPLI = 226.49
