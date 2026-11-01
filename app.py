import os
import math
import time
import requests
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================================
# BTTS V6 - FOOTBALL INTELLIGENCE
# ==========================================================

st.set_page_config(
    page_title="BTTS V6",
    page_icon="⚽",
    layout="wide"
)

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
TZ = ZoneInfo("Africa/Abidjan")

DEFAULT_ANALYSES = 10
MAX_RECOMMENDATIONS = 3
HISTORY_REQUEST_SIZE = 20
MIN_HISTORY = 5

st.title("⚽ BTTS V6 - Football Intelligence")
st.caption(
    "Analyse statistique automatique | BTTS Oui/Non | "
    "Probabilité que chaque équipe marque | Top 3"
)

if not API_KEY:
    st.error(
        "Clé API absente. Dans Render > Environment, vérifie "
        "que API_FOOTBALL_KEY existe. Ne colle jamais ta clé dans le code."
    )
    st.stop()

HEADERS = {"x-apisports-key": API_KEY}


# ==========================================================
# CLIENT API ET SUIVI DU QUOTA
# ==========================================================

def api_request(endpoint, params):
    try:
        response = requests.get(
            BASE_URL + endpoint,
            headers=HEADERS,
            params=params,
            timeout=25
        )

        # Les en-têtes peuvent indiquer le quota restant.
        remaining_day = response.headers.get("x-ratelimit-requests-remaining")
        remaining_minute = response.headers.get("X-RateLimit-Remaining")

        if remaining_day is not None:
            st.session_state["api_remaining_day"] = remaining_day
        if remaining_minute is not None:
            st.session_state["api_remaining_minute"] = remaining_minute

        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            raise RuntimeError(str(data["errors"]))

        return data.get("response", [])

    except requests.exceptions.HTTPError as error:
        status = error.response.status_code if error.response is not None else "inconnu"
        raise RuntimeError(
            f"API-Football HTTP {status}. Vérifie la clé, le forfait "
            "et le quota disponible."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Délai dépassé lors de la connexion à API-Football.")
    except Exception as error:
        raise RuntimeError(f"Erreur API : {error}")


@st.cache_data(ttl=60, show_spinner=False)
def get_today_matches(date):
    return api_request(
        "/fixtures",
        {"date": date, "timezone": "Africa/Abidjan"}
    )


@st.cache_data(ttl=21600, show_spinner=False)
def get_team_history(team_id):
    # Cache 6 heures : évite de redemander sans cesse les mêmes historiques.
    time.sleep(0.40)

    fixtures = api_request(
        "/fixtures",
        {
            "team": team_id,
            "last": HISTORY_REQUEST_SIZE,
            "timezone": "Africa/Abidjan"
        }
    )

    finished = [
        item for item in fixtures
        if item.get("fixture", {}).get("status", {}).get("short")
        in ("FT", "AET", "PEN")
        and item.get("goals", {}).get("home") is not None
        and item.get("goals", {}).get("away") is not None
    ]

    finished.sort(
        key=lambda item: item.get("fixture", {}).get("date", ""),
        reverse=True
    )
    return finished[:10]


# ==========================================================
# STATISTIQUES HISTORIQUES
# ==========================================================

def extract_team_stats(fixtures, team_id):
    stats = []

    for item in fixtures:
        teams = item.get("teams", {})
        goals = item.get("goals", {})

        if teams.get("home", {}).get("id") == team_id:
            scored = goals.get("home")
            conceded = goals.get("away")
            venue = "home"
        elif teams.get("away", {}).get("id") == team_id:
            scored = goals.get("away")
            conceded = goals.get("home")
            venue = "away"
        else:
            continue

        if scored is None or conceded is None:
            continue

        stats.append({
            "scored": int(scored),
            "conceded": int(conceded),
            "btts": int(scored > 0 and conceded > 0),
            "total": int(scored + conceded),
            "venue": venue
        })

    return stats


def average_stats(items):
    if not items:
        return None

    count = len(items)
    return {
        "count": count,
        "scored": sum(x["scored"] for x in items) / count,
        "conceded": sum(x["conceded"] for x in items) / count,
        "btts": sum(x["btts"] for x in items) / count,
        "total": sum(x["total"] for x in items) / count
    }


def build_team_profile(fixtures, team_id):
    stats = extract_team_stats(fixtures, team_id)

    if len(stats) < MIN_HISTORY:
        return None

    home_items = [x for x in stats if x["venue"] == "home"]
    away_items = [x for x in stats if x["venue"] == "away"]

    return {
        "last5": average_stats(stats[:5]),
        "last10": average_stats(stats[:10]),
        # N'utilise les statistiques domicile/extérieur que si
        # au moins 3 rencontres sont disponibles dans ce contexte.
        "home": average_stats(home_items) if len(home_items) >= 3 else None,
        "away": average_stats(away_items) if len(away_items) >= 3 else None,
        "count": len(stats)
    }


# ==========================================================
# PROBABILITÉS - MODÈLE DE POISSON SIMPLIFIÉ
# ==========================================================

def poisson_probabilities(expected_home, expected_away):
    p_home_scores = 1 - math.exp(-expected_home)
    p_away_scores = 1 - math.exp(-expected_away)

    p_btts_yes = p_home_scores * p_away_scores
    p_btts_no = 1 - p_btts_yes

    return {
        "home_scores": p_home_scores,
        "away_scores": p_away_scores,
        "btts_yes": p_btts_yes,
        "btts_no": p_btts_no
    }


# ==========================================================
# MOTEUR D'ANALYSE
# ==========================================================

def analyze_fixture(fixture):
    teams = fixture.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return {"ok": False, "reason": "Identifiants des équipes manquants."}

    home_history = get_team_history(home_id)
    away_history = get_team_history(away_id)

    hp = build_team_profile(home_history, home_id)
    ap = build_team_profile(away_history, away_id)

    if hp is None or ap is None:
        h_count = len(extract_team_stats(home_history, home_id))
        a_count = len(extract_team_stats(away_history, away_id))
        return {
            "ok": False,
            "reason": (
                f"Historique insuffisant : {home.get('name', 'Domicile')} "
                f"{h_count}/{MIN_HISTORY}, {away.get('name', 'Extérieur')} "
                f"{a_count}/{MIN_HISTORY} matchs terminés."
            )
        }

    h5, h10 = hp["last5"], hp["last10"]
    a5, a10 = ap["last5"], ap["last10"]

    home_context = hp["home"] or h10
    away_context = ap["away"] or a10

    expected_home = (
        0.60 * home_context["scored"]
        + 0.40 * away_context["conceded"]
    )
    expected_away = (
        0.60 * away_context["scored"]
        + 0.40 * home_context["conceded"]
    )

    expected_home = (
        0.75 * expected_home
        + 0.25 * (0.60 * h5["scored"] + 0.40 * a5["conceded"])
    )
    expected_away = (
        0.75 * expected_away
        + 0.25 * (0.60 * a5["scored"] + 0.40 * h5["conceded"])
    )

    expected_home = max(0.05, min(expected_home, 4.0))
    expected_away = max(0.05, min(expected_away, 4.0))

    probs = poisson_probabilities(expected_home, expected_away)
    yes = probs["btts_yes"]
    no = probs["btts_no"]

    yes_filters = [
        h10["count"] >= 5 and a10["count"] >= 5,
        h5["btts"] >= 0.40,
        a5["btts"] >= 0.40,
        expected_home >= 0.80 and expected_away >= 0.80,
        h10["conceded"] >= 0.70 and a10["conceded"] >= 0.70,
        h10["total"] >= 2.0 and a10["total"] >= 2.0,
        yes >= 0.60
    ]

    no_filters = [
        h10["count"] >= 5 and a10["count"] >= 5,
        h10["btts"] <= 0.50,
        a10["btts"] <= 0.50,
        expected_home < 1.50 or expected_away < 1.50,
        h10["scored"] < 1.60 or a10["scored"] < 1.60,
        no >= 0.65,
        no >= 0.70
    ]

    yes_score = sum(yes_filters)
    no_score = sum(no_filters)

    decision = "AUCUN"
    if yes >= 0.65 and yes_score >= 6:
        decision = "BTTS OUI"
    elif no >= 0.70 and no_score >= 6:
        decision = "BTTS NON"

    # Indicateur de volume de données, pas une garantie de réussite.
    history_count = min(hp["count"], ap["count"])
    if history_count >= 10:
        data_quality = "Bonne quantité d'historique"
    else:
        data_quality = "Historique limité"

    return {
        "ok": True,
        "fixture_id": fixture.get("fixture", {}).get("id"),
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_logo": home.get("logo"),
        "away_logo": away.get("logo"),
        "league": fixture.get("league", {}).get("name", ""),
        "kickoff": fixture.get("fixture", {}).get("date", ""),
        "yes": round(yes * 100, 1),
        "no": round(no * 100, 1),
        "home_scores": round(probs["home_scores"] * 100, 1),
        "away_scores": round(probs["away_scores"] * 100, 1),
        "expected_home": round(expected_home, 2),
        "expected_away": round(expected_away, 2),
        "yes_score": yes_score,
        "no_score": no_score,
        "decision": decision,
        "yes_filters": yes_filters,
        "no_filters": no_filters,
        "home_history": hp["count"],
        "away_history": ap["count"],
        "home_btts_last5": round(h5["btts"] * 100, 1),
        "away_btts_last5": round(a5["btts"] * 100, 1),
        "data_quality": data_quality
    }


# ==========================================================
# COMPOSANTS D'AFFICHAGE
# ==========================================================

def render_fixture_card(fixture):
    teams = fixture.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})
    fixture_info = fixture.get("fixture", {})
    kickoff = fixture_info.get("date", "")

    with st.container(border=True):
        left, middle, right = st.columns([2, 1, 2])
        with left:
            if home.get("logo"):
                st.image(home["logo"], width=48)
            st.write(home.get("name", "Domicile"))
        with middle:
            st.markdown("### VS")
            st.caption(kickoff[11:16] if len(kickoff) >= 16 else "Heure N/D")
        with right:
            if away.get("logo"):
                st.image(away["logo"], width=48)
            st.write(away.get("name", "Extérieur"))


def render_analysis(result):
    with st.container(border=True):
        st.subheader(f"{result['home']} – {result['away']}")
        st.caption(f"{result['league']} | {result['data_quality']}")

        left, right = st.columns(2)
        with left:
            st.metric("BTTS OUI", f"{result['yes']} %")
            st.metric(
                f"{result['home']} marque au moins 1 but",
                f"{result['home_scores']} %"
            )
        with right:
            st.metric("BTTS NON", f"{result['no']} %")
            st.metric(
                f"{result['away']} marque au moins 1 but",
                f"{result['away_scores']} %"
            )

        st.write(
            f"**Buts attendus :** {result['home']} "
            f"{result['expected_home']} – {result['expected_away']} "
            f"{result['away']}"
        )
        st.write(
            f"**BTTS sur les 5 derniers matchs :** "
            f"{result['home_btts_last5']} % – "
            f"{result['away_btts_last5']} %"
        )
        st.write(
            f"**Historique :** {result['home_history']} matchs "
            f"pour {result['home']} ; {result['away_history']} "
            f"pour {result['away']}"
        )
        st.write(
            f"**Décision : {result['decision']}** | "
            f"Filtres OUI {result['yes_score']}/7 | "
            f"Filtres NON {result['no_score']}/7"
        )

        with st.expander("Voir les filtres statistiques"):
            st.write("Filtres BTTS OUI")
            for number, passed in enumerate(result["yes_filters"], 1):
                st.write(f"{'✅' if passed else '❌'} Filtre {number}")
            st.write("Filtres BTTS NON")
            for number, passed in enumerate(result["no_filters"], 1):
                st.write(f"{'✅' if passed else '❌'} Filtre {number}")


# ==========================================================
# TABLEAU DE BORD - RAFRAÎCHISSEMENT 60 SECONDES
# ==========================================================

@st.fragment(run_every="60s")
def dashboard():
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")

    st.caption(
        f"Date : {now.strftime('%d/%m/%Y')} | "
        f"Dernière actualisation : {now.strftime('%H:%M:%S')} "
        "(heure de Côte d'Ivoire)"
    )

    try:
        fixtures = get_today_matches(today)
    except Exception as error:
        st.error(str(error))
        return

    st.subheader(f"📅 Matchs répertoriés aujourd'hui : {len(fixtures)}")

    upcoming = [
        f for f in fixtures
        if f.get("fixture", {}).get("status", {}).get("short") in ("NS", "TBD")
    ]
    upcoming.sort(key=lambda f: f.get("fixture", {}).get("date", ""))

    st.write(f"Matchs à venir : **{len(upcoming)}**")

    # Affiche le quota seulement si l'API renvoie les en-têtes correspondants.
    q1, q2 = st.columns(2)
    with q1:
        st.caption(
            "Requêtes API restantes aujourd'hui : "
            + str(st.session_state.get("api_remaining_day", "non communiqué"))
        )
    with q2:
        st.caption(
            "Requêtes restantes cette minute : "
            + str(st.session_state.get("api_remaining_minute", "non communiqué"))
        )

    with st.expander("📋 Afficher la liste des matchs du jour"):
        if fixtures:
            for fixture in fixtures:
                render_fixture_card(fixture)
        else:
            st.info("Aucun match trouvé pour cette date.")

    st.divider()
    st.subheader("🧠 Analyses automatiques BTTS V6")

    analysis_count = st.selectbox(
        "Nombre de matchs à analyser par actualisation",
        options=[5, 10, 15],
        index=1,
        key="v6_analysis_count"
    )
    st.caption(
        "Pour économiser le quota, commence avec 10. "
        "Les historiques des équipes sont mis en cache pendant 6 heures."
    )

    candidates = upcoming[:analysis_count]

    if not candidates:
        st.info("Aucun match à venir à analyser actuellement.")
        return

    results = []
    errors = []
    progress = st.progress(0)
    message = st.empty()

    for index, fixture in enumerate(candidates):
        teams = fixture.get("teams", {})
        home_name = teams.get("home", {}).get("name", "Domicile")
        away_name = teams.get("away", {}).get("name", "Extérieur")

        message.write(
            f"Analyse {index + 1}/{len(candidates)} : "
            f"{home_name} – {away_name}"
        )

        try:
            result = analyze_fixture(fixture)
            if result.get("ok"):
                results.append(result)
            else:
                errors.append((home_name, away_name, result.get("reason", "Données insuffisantes")))
        except Exception as error:
            errors.append((home_name, away_name, str(error)))

        progress.progress((index + 1) / len(candidates))

    progress.empty()
    message.empty()

    st.write(
        f"Analyses complètes : **{len(results)}** | "
        f"Analyses indisponibles : **{len(errors)}**"
    )

    if results:
        for result in results:
            render_analysis(result)
    else:
        st.warning(
            "Aucune analyse complète pour les matchs sélectionnés. "
            "Les raisons sont affichées ci-dessous."
        )

    if errors:
        with st.expander("⚠️ Matchs sans analyse complète et raisons"):
            for home_name, away_name, reason in errors:
                st.write(f"**{home_name} – {away_name} :** {reason}")

    # Top 3 : aucune sélection forcée.
    recommendations = [r for r in results if r["decision"] != "AUCUN"]
    recommendations.sort(
        key=lambda r: (
            r["yes_score"] if r["decision"] == "BTTS OUI" else r["no_score"],
            r["yes"] if r["decision"] == "BTTS OUI" else r["no"]
        ),
        reverse=True
    )

    st.divider()
    st.subheader("🏆 TOP 3 - SÉLECTIONS QUI PASSENT LES FILTRES")

    if not recommendations:
        st.info(
            "Aucune sélection ne passe les critères. "
            "Le moteur préfère ne rien recommander plutôt que forcer un pari."
        )
    else:
        for rank, result in enumerate(recommendations[:MAX_RECOMMENDATIONS], 1):
            st.success(
                f"#{rank} — {result['home']} vs {result['away']}\n\n"
                f"Décision : {result['decision']}\n\n"
                f"BTTS OUI : {result['yes']} % | BTTS NON : {result['no']} %\n\n"
                f"Chance que chaque équipe marque au moins un but : "
                f"{result['home']} {result['home_scores']} % ; "
                f"{result['away']} {result['away_scores']} %"
            )

    st.caption(
        "Limites : probabilités statistiques indicatives issues d'un "
        "modèle simplifié de Poisson et des derniers résultats disponibles. "
        "Elles ne garantissent pas le résultat. « Équipe qui marque » "
        "désigne la probabilité qu'une équipe inscrive au moins un but, "
        "pas le nom d'un joueur buteur. Les compositions, blessures et "
        "changements tactiques ne sont pas intégrés automatiquement."
    )


# ==========================================================
# DÉMARRAGE
# ==========================================================

dashboard()
