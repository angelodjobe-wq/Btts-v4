
import os
import time
import math
import json
import threading
import requests
import streamlit as st
import pandas as pd

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler

# =========================================
# BTTS V4 ULTRA ENGINE
# =========================================

TZ = ZoneInfo("Africa/Abidjan")
BASE = "https://v3.football.api-sports.io"
API_KEY = os.getenv("API_FOOTBALL_KEY")

MIN_PROB = 80
TOP_N = 5
MAX_FIXTURES = 60

HEADERS = {"x-apisports-key": API_KEY or ""}

st.set_page_config(
    page_title="BTTS V4 ULTRA",
    page_icon="⚽",
    layout="wide"
)

# Shared application cache
if "daily_results" not in st.session_state:
    st.session_state.daily_results = None

if "last_update" not in st.session_state:
    st.session_state.last_update = None

if "analysis_error" not in st.session_state:
    st.session_state.analysis_error = None

# =========================================
# API REQUESTS
# =========================================

def api_get(endpoint, params=None):
    try:
        response = requests.get(
            BASE + endpoint,
            headers=HEADERS,
            params=params or {},
            timeout=25
        )
        response.raise_for_status()

        data = response.json()

        if data.get("errors"):
            return []

        return data.get("response", [])

    except Exception as error:
        print("API ERROR:", error)
        return []


# =========================================
# MATCHES OF THE DAY
# =========================================

def get_fixtures(date):
    return api_get(
        "/fixtures",
        {
            "date": date,
            "timezone": "Africa/Abidjan"
        }
    )


# =========================================
# LAST 10 MATCHES
# =========================================

team_cache = {}

def get_team_history(team_id):

    if team_id in team_cache:
        return team_cache[team_id]

    matches = api_get(
        "/fixtures",
        {
            "team": team_id,
            "last": 10,
            "status": "FT",
            "timezone": "Africa/Abidjan"
        }
    )

    team_cache[team_id] = matches

    time.sleep(0.25)

    return matches


def analyze_team(team_id):

    matches = get_team_history(team_id)

    data = []

    for match in matches:

        goals = match.get("goals", {})
        teams = match.get("teams", {})

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        is_home = teams["home"]["id"] == team_id

        scored = home_goals if is_home else away_goals
        conceded = away_goals if is_home else home_goals

        data.append({
            "scored": scored,
            "conceded": conceded,
            "btts": int(scored > 0 and conceded > 0),
            "home": is_home
        })

    if len(data) < 8:
        return None

    df = pd.DataFrame(data)

    return {
        "matches": len(df),
        "attack": df.scored.mean(),
        "defense": df.conceded.mean(),
        "scored_rate": (df.scored > 0).mean(),
        "conceded_rate": (df.conceded > 0).mean(),
        "btts": df.btts.mean(),
        "recent": df.head(5).btts.mean(),
        "home_data": df[df.home],
        "away_data": df[~df.home]
    }


# =========================================
# POISSON MODEL
# =========================================

def probability_btts(home_goals, away_goals):

    p_home = 1 - math.exp(-home_goals)
    p_away = 1 - math.exp(-away_goals)

    yes = p_home * p_away

    return yes, 1 - yes


# =========================================
# SECOND OPINION: API-FOOTBALL
# =========================================

def get_api_prediction(fixture_id):

    result = api_get(
        "/predictions",
        {"fixture": fixture_id}
    )

    if not result:
        return None

    return result[0].get("predictions", {})


# =========================================
# ADVANCED MATCH ENGINE
# =========================================

def analyze_match(fixture):

    teams = fixture.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    if not home.get("id") or not away.get("id"):
        return None

    h = analyze_team(home["id"])
    a = analyze_team(away["id"])

    if h is None or a is None:
        return None

    # Home and away expected goals
    home_lambda = (
        h["attack"] * 0.55 +
        a["defense"] * 0.45
    )

    away_lambda = (
        a["attack"] * 0.55 +
        h["defense"] * 0.45
    )

    if len(h["home_data"]) >= 3:
        home_lambda = (
            home_lambda * 0.65 +
            h["home_data"].scored.mean() * 0.35
        )

    if len(a["away_data"]) >= 3:
        away_lambda = (
            away_lambda * 0.65 +
            a["away_data"].scored.mean() * 0.35
        )

    home_lambda = max(0.05, min(4, home_lambda))
    away_lambda = max(0.05, min(4, away_lambda))

    yes, no = probability_btts(
        home_lambda,
        away_lambda
    )

    historical_yes = (h["btts"] + a["btts"]) / 2
    recent_yes = (h["recent"] + a["recent"]) / 2

    # Combined statistical estimates
    yes_probability = (
        yes * 0.50 +
        historical_yes * 0.30 +
        recent_yes * 0.20
    )

    no_probability = 1 - yes_probability

    # Risk controls
    risks = []

    if h["matches"] < 10 or a["matches"] < 10:
        risks.append("Historique incomplet")

    if h["scored_rate"] < 0.60:
        risks.append("Attaque domicile faible")

    if a["scored_rate"] < 0.60:
        risks.append("Attaque extérieur faible")

    if h["recent"] < 0.40 or a["recent"] < 0.40:
        risks.append("Tendance BTTS récente faible")

    # API prediction is a separate opinion,
    # not a fabricated BTTS percentage.
    fixture_id = fixture.get("fixture", {}).get("id")
    api_prediction = get_api_prediction(fixture_id)

    return {
        "fixture_id": fixture_id,
        "home": home.get("name"),
        "away": away.get("name"),
        "league": fixture.get("league", {}).get("name"),
        "time": fixture.get("fixture", {}).get("date"),
        "yes": round(yes_probability * 100, 1),
        "no": round(no_probability * 100, 1),
        "poisson": round(yes * 100, 1),
        "historical": round(historical_yes * 100, 1),
        "recent": round(recent_yes * 100, 1),
        "home_lambda": round(home_lambda, 2),
        "away_lambda": round(away_lambda, 2),
        "risks": risks,
        "api_advice": (
            api_prediction.get("advice", "Non disponible")
            if api_prediction else "Non disponible"
        )
    }


# =========================================
# DAILY ANALYSIS
# =========================================

def run_daily_analysis():

    global team_cache

    team_cache = {}

    today = datetime.now(TZ).strftime("%Y-%m-%d")

    fixtures = get_fixtures(today)

    results = []

    # Analyse all available competitions
    # with a controlled API request budget.
    candidates = [
        f for f in fixtures
        if f.get("fixture", {}).get("status", {}).get("short") == "NS"
    ][:MAX_FIXTURES]

    for index, fixture in enumerate(candidates):

        try:
            result = analyze_match(fixture)

            if result:
                results.append(result)

        except Exception as error:
            print("MATCH ERROR:", error)

        time.sleep(0.3)

    # Both BTTS markets are considered.
    selections = []

    for match in results:

        if match["yes"] >= MIN_PROB:
            selections.append({
                **match,
                "market": "BTTS OUI",
                "probability": match["yes"]
            })

        if match["no"] >= MIN_PROB:
            selections.append({
                **match,
                "market": "BTTS NON",
                "probability": match["no"]
            })

    selections.sort(
        key=lambda x: x["probability"],
        reverse=True
    )

    # Do not duplicate the same match.
    final = []
    seen = set()

    for item in selections:
        if item["fixture_id"] in seen:
            continue

        seen.add(item["fixture_id"])

        if len(final) == TOP_N:
            break

        final.append(item)

    return {
        "date": today,
        "matches_scanned": len(candidates),
        "analyzed": len(results),
        "top5": final
    }


# =========================================
# AUTOMATIC SCHEDULER
# =========================================

cache_lock = threading.Lock()
daily_cache = {
    "date": None,
    "data": None,
    "updated": None
}


def scheduled_analysis():

    now = datetime.now(TZ)

    if now.hour < 7:
        return

    with cache_lock:

        date = now.strftime("%Y-%m-%d")

        if daily_cache["date"] == date:
            return

        print("BTTS V4: Daily analysis started")

        data = run_daily_analysis()

        daily_cache["date"] = date
        daily_cache["data"] = data
        daily_cache["updated"] = now.isoformat()

        print("BTTS V4: Daily analysis completed")


@st.cache_resource
def start_scheduler():

    scheduler = BackgroundScheduler(
        timezone=TZ
    )

    scheduler.add_job(
        scheduled_analysis,
        "cron",
        hour=7,
        minute=0,
        id="daily_analysis",
        replace_existing=True,
        max_instances=1
    )

    scheduler.start()

    return scheduler


scheduler = start_scheduler()


# =========================================
# DASHBOARD
# =========================================

st.title("⚽ BTTS V4 ULTRA ENGINE")

st.caption(
    "Intelligence statistique | Toutes les divisions disponibles"
)

if not API_KEY:
    st.error("API_FOOTBALL_KEY absente dans Render.")
    st.stop()

st.info(
    "Actualisation quotidienne programmée à 7 h. "
    "Les analyses sont destinées à être disponibles avant 8 h."
)

with cache_lock:
    data = daily_cache["data"]
    updated = daily_cache["updated"]

if st.button("Actualiser les analyses maintenant"):

    with st.spinner("Analyse des rencontres en cours..."):

        new_data = run_daily_analysis()

        with cache_lock:
            daily_cache["date"] = new_data["date"]
            daily_cache["data"] = new_data
            daily_cache["updated"] = datetime.now(TZ).isoformat()

        data = new_data
        updated = daily_cache["updated"]

if data is None:

    st.warning(
        "Les analyses du jour ne sont pas encore disponibles. "
        "Le moteur attend sa première exécution."
    )

else:

    st.success(
        f"Analyse du {data['date']} | "
        f"{data['analyzed']} matchs analysés"
    )

    if updated:
        st.caption(f"Dernière actualisation : {updated}")

    st.subheader("🏆 TOP 5 DU JOUR")

    if not data["top5"]:

        st.warning(
            "Aucun match ne satisfait les critères de sélection "
            "à 80 %. Le moteur ne force aucune sélection."
        )

    for rank, match in enumerate(data["top5"], 1):

        with st.container(border=True):

            st.markdown(
                f"### {rank}. {match['home']} - {match['away']}"
            )

            st.write(f"Championnat : {match['league']}")

            st.metric(
                match["market"],
                f"{match['probability']} %"
            )

            st.write(
                f"Poisson : {match['poisson']} % | "
                f"Historique : {match['historical']} %"
            )

            st.write(
                f"Tendance récente : {match['recent']} %"
            )

            st.write(
                f"Buts attendus : {match['home_lambda']} - "
                f"{match['away_lambda']}"
            )

            st.write(
                f"Deuxième avis API-Football : "
                f"{match['api_advice']}"
            )

            if match["risks"]:
                st.warning("Risques : " + ", ".join(match["risks"]))
            else:
                st.success("Filtres historiques validés")

    st.caption(
        "80 % est un seuil de sélection du modèle, "
        "pas une garantie de résultat."
    )

st.divider()

st.write("Matchs récupérés :", data["matches_scanned"] if data else 0)
st.write("Matchs analysés :", data["analyzed"] if data else 0)
