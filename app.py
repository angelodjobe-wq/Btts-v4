
import os
import math
import time
import requests
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# BTTS V5 - MOTEUR AUTOMATIQUE
# ==========================================

st.set_page_config(
    page_title="BTTS V5",
    page_icon="⚽",
    layout="wide"
)

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
TZ = ZoneInfo("Africa/Abidjan")

st.title("⚽ BTTS V5 - Football Intelligence")
st.caption("Analyse automatique | Actualisation chaque minute")

if not API_KEY:
    st.error("Clé API absente : vérifie API_FOOTBALL_KEY dans Render.")
    st.stop()

HEADERS = {"x-apisports-key": API_KEY}

# Réglages pour maîtriser le quota
MAX_ANALYSES = 10
MAX_RECOMMENDATIONS = 3


# ==========================================
# API FOOTBALL
# ==========================================

def api_request(endpoint, params):
    try:
        response = requests.get(
            BASE_URL + endpoint,
            headers=HEADERS,
            params=params,
            timeout=25
        )
        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            raise RuntimeError(str(data["errors"]))

        return data.get("response", [])

    except Exception as error:
        raise RuntimeError(f"Erreur API : {error}")


@st.cache_data(ttl=60, show_spinner=False)
def get_today_matches(date):
    return api_request(
        "/fixtures",
        {
            "date": date,
            "timezone": "Africa/Abidjan"
        }
    )


@st.cache_data(ttl=21600, show_spinner=False)
def get_team_history(team_id):
    time.sleep(0.35)

    fixtures = api_request(
        "/fixtures",
        {
            "team": team_id,
            "last": 10,
            "timezone": "Africa/Abidjan"
        }
    )

    return [
        f for f in fixtures
        if f.get("fixture", {}).get("status", {}).get("short")
        in ["FT", "AET", "PEN"]
        and f.get("goals", {}).get("home") is not None
        and f.get("goals", {}).get("away") is not None
    ]


# ==========================================
# STATISTIQUES DES ÉQUIPES
# ==========================================

def extract_team_stats(fixtures, team_id):
    result = []

    for match in fixtures:
        teams = match["teams"]
        goals = match["goals"]

        if teams["home"]["id"] == team_id:
            scored = goals["home"]
            conceded = goals["away"]
            venue = "home"

        elif teams["away"]["id"] == team_id:
            scored = goals["away"]
            conceded = goals["home"]
            venue = "away"

        else:
            continue

        result.append({
            "scored": scored,
            "conceded": conceded,
            "btts": int(scored > 0 and conceded > 0),
            "total": scored + conceded,
            "venue": venue
        })

    return result


def average_stats(matches):
    if len(matches) < 1:
        return None

    n = len(matches)

    return {
        "count": n,
        "scored": sum(x["scored"] for x in matches) / n,
        "conceded": sum(x["conceded"] for x in matches) / n,
        "btts": sum(x["btts"] for x in matches) / n,
        "total": sum(x["total"] for x in matches) / n
    }


def team_profile(fixtures, team_id):
    stats = extract_team_stats(fixtures, team_id)

    if len(stats) < 5:
        return None

    last5 = average_stats(stats[:5])
    last10 = average_stats(stats[:10])

    home_stats = average_stats([
        x for x in stats if x["venue"] == "home"
    ])

    away_stats = average_stats([
        x for x in stats if x["venue"] == "away"
    ])

    return {
        "last5": last5,
        "last10": last10,
        "home": home_stats,
        "away": away_stats
    }


# ==========================================
# MODÈLE DE POISSON
# ==========================================

def calculate_btts(lambda_home, lambda_away):
    p_home = 1 - math.exp(-lambda_home)
    p_away = 1 - math.exp(-lambda_away)

    yes = p_home * p_away
    no = 1 - yes

    return yes, no


# ==========================================
# NOUVEAU MOTEUR BTTS V5
# ==========================================

def analyze_match_v5(fixture):

    teams = fixture.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    home_id = home.get("id")
    away_id = away.get("id")

    if not home_id or not away_id:
        return None

    home_history = get_team_history(home_id)
    away_history = get_team_history(away_id)

    home_data = team_profile(home_history, home_id)
    away_data = team_profile(away_history, away_id)

    if home_data is None or away_data is None:
        return None

    h5 = home_data["last5"]
    h10 = home_data["last10"]
    a5 = away_data["last5"]
    a10 = away_data["last10"]

    # Domicile et extérieur avec repli sur les 10 derniers matchs
    home_venue = home_data["home"] or h10
    away_venue = away_data["away"] or a10

    # Estimation offensive et défensive
    lh = (
        0.60 * home_venue["scored"]
        + 0.40 * away_venue["conceded"]
    )

    la = (
        0.60 * away_venue["scored"]
        + 0.40 * home_venue["conceded"]
    )

    # Correction par la forme récente
    lh = 0.75 * lh + 0.25 * (
        0.60 * h5["scored"] + 0.40 * a5["conceded"]
    )

    la = 0.75 * la + 0.25 * (
        0.60 * a5["scored"] + 0.40 * h5["conceded"]
    )

    # Protection des valeurs
    lh = max(0.05, min(lh, 4.0))
    la = max(0.05, min(la, 4.0))

    yes, no = calculate_btts(lh, la)

    # Sept filtres BTTS OUI
    yes_filters = [
        h10["count"] >= 5 and a10["count"] >= 5,
        h5["btts"] >= 0.40,
        a5["btts"] >= 0.40,
        lh >= 0.80 and la >= 0.80,
        h10["conceded"] >= 0.70 and a10["conceded"] >= 0.70,
        h10["total"] >= 2.0 and a10["total"] >= 2.0,
        yes >= 0.60
    ]

    # Sept filtres BTTS NON
    no_filters = [
        h10["count"] >= 5 and a10["count"] >= 5,
        h10["btts"] <= 0.50,
        a10["btts"] <= 0.50,
        lh < 1.50 or la < 1.50,
        h10["scored"] < 1.60 or a10["scored"] < 1.60,
        no >= 0.65,
        no >= 0.70
    ]

    yes_score = sum(yes_filters)
    no_score = sum(no_filters)

    prediction = "AUCUN"

    if yes >= 0.65 and yes_score >= 6:
        prediction = "BTTS OUI"

    elif no >= 0.70 and no_score >= 6:
        prediction = "BTTS NON"

    return {
        "home": home.get("name", "Domicile"),
        "away": away.get("name", "Extérieur"),
        "home_logo": home.get("logo"),
        "away_logo": away.get("logo"),
        "league": fixture.get("league", {}).get("name", ""),
        "date": fixture.get("fixture", {}).get("date", ""),
        "yes": round(yes * 100, 1),
        "no": round(no * 100, 1),
        "yes_score": yes_score,
        "no_score": no_score,
        "prediction": prediction,
        "lambda_home": round(lh, 2),
        "lambda_away": round(la, 2),
        "yes_filters": yes_filters,
        "no_filters": no_filters
    }


# ==========================================
# AFFICHAGE AUTOMATIQUE
# ==========================================

@st.fragment(run_every="60s")
def automatic_dashboard():

    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")

    st.caption(
        f"Date : {now.strftime('%d/%m/%Y')} | "
        f"Dernière actualisation : {now.strftime('%H:%M:%S')}"
    )

    try:
        matches = get_today_matches(today)

    except Exception as error:
        st.error(str(error))
        return

    st.subheader(f"📅 Matchs du jour : {len(matches)}")

    if not matches:
        st.info("Aucun match disponible pour aujourd'hui.")
        return

    # Affichage des matchs et logos
    upcoming = []

    for match in matches:
        fixture = match.get("fixture", {})
        status = fixture.get("status", {}).get("short")
        home = match.get("teams", {}).get("home", {})
        away = match.get("teams", {}).get("away", {})

        if status in ["NS", "TBD"]:
            upcoming.append(match)

        with st.container(border=True):
            col1, col2, col3 = st.columns([2, 1, 2])

            with col1:
                if home.get("logo"):
                    st.image(home["logo"], width=55)
                st.write(home.get("name", "Domicile"))

            with col2:
                st.write("VS")
                st.caption(
                    fixture.get("date", "")[11:16]
                    if fixture.get("date") else ""
                )

            with col3:
                if away.get("logo"):
                    st.image(away["logo"], width=55)
                st.write(away.get("name", "Extérieur"))

    st.divider()
    st.subheader("🧠 Analyses automatiques BTTS V5")

    candidates = sorted(
        upcoming,
        key=lambda x: x.get("fixture", {}).get("date", "")
    )[:MAX_ANALYSES]

    results = []

    progress = st.progress(0)

    for index, match in enumerate(candidates):
        try:
            result = analyze_match_v5(match)

            if result:
                results.append(result)

        except Exception as error:
            st.warning(f"Une analyse a échoué : {error}")

        progress.progress((index + 1) / len(candidates))

    progress.empty()

    if not results:
        st.warning(
            "Données historiques insuffisantes. "
            "Les matchs restent affichés, mais aucune prédiction "
            "fiable ne peut être produite."
        )
        return

    # Résultats individuels
    for result in results:
        with st.expander(
            f"{result['home']} - {result['away']} | "
            f"{result['prediction']}"
        ):
            st.write(f"Compétition : {result['league']}")
            st.write(f"BTTS OUI : {result['yes']} %")
            st.write(f"BTTS NON : {result['no']} %")
            st.write(
                f"Filtres OUI : {result['yes_score']}/7"
            )
            st.write(
                f"Filtres NON : {result['no_score']}/7"
            )
            st.write(
                f"Buts attendus : {result['lambda_home']} - "
                f"{result['lambda_away']}"
            )

            st.write("Filtres OUI :")
            for i, passed in enumerate(result["yes_filters"], 1):
                st.write(f"{'✅' if passed else '❌'} Filtre {i}")

            st.write("Filtres NON :")
            for i, passed in enumerate(result["no_filters"], 1):
                st.write(f"{'✅' if passed else '❌'} Filtre {i}")

    # Trois meilleures sélections maximum
    recommendations = [
        r for r in results if r["prediction"] != "AUCUN"
    ]

    recommendations.sort(
        key=lambda r: (
            r["yes_score"] if r["prediction"] == "BTTS OUI"
            else r["no_score"],
            r["yes"] if r["prediction"] == "BTTS OUI"
            else r["no"]
        ),
        reverse=True
    )

    st.divider()
    st.subheader("🏆 TOP 3 BTTS V5")

    if not recommendations:
        st.info(
            "Aucune rencontre ne passe les critères. "
            "Le moteur ne force aucune sélection."
        )

    for number, result in enumerate(
        recommendations[:MAX_RECOMMENDATIONS], 1
    ):
        st.success(
            f"#{number} — {result['home']} vs {result['away']}\n\n"
            f"Prédiction : {result['prediction']}\n\n"
            f"BTTS OUI : {result['yes']} % | "
            f"BTTS NON : {result['no']} %"
        )

    st.caption(
        "Les probabilités sont des estimations statistiques, "
        "jamais des garanties de résultat."
    )


# ==========================================
# LANCEMENT
# ==========================================

automatic_dashboard()
tj
