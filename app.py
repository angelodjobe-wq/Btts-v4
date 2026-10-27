import os
import streamlit as st
import requests
from datetime import datetime

st.set_page_config(page_title="BTTS V5.2", layout="wide", page_icon="⚽")

API_KEY = os.getenv("API_FOOTBALL_KEY") or os.getenv("API_KEY") or ""
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

if not API_KEY:
    st.error("🔴 Clé API manquante")
    st.stop()

def api_call(endpoint, params):
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
        data = r.json()
        if "errors" in data and data["errors"]:
            if "suspended" in str(data["errors"]).lower():
                st.error("🔴 Compte API-Football suspendu")
                st.stop()
        return data
    except Exception as e:
        st.error(f"Erreur API: {e}")
        return None

st.title("⚽ ANGELO V5.2 - MOTEUR TOTAL")
st.caption("Moteur d'Analyse Statistique | BTTS • BUTS • CORNERS")
st.divider()

st.subheader("📅 Matchs du Jour (Abidjan)")
date_str = datetime.now().strftime("%Y-%m-%d")
fixtures_data = api_call("fixtures", {"date": date_str, "timezone": "Africa/Abidjan"})

if not fixtures_data or not fixtures_data.get("response"):
    st.warning("Aucun match aujourd'hui.")
    st.stop()

fixtures = fixtures_data["response"]
fixture_options = {}
for f in fixtures:
    key = f"{f['fixture']['id']} - {f['teams']['home']['name']} vs {f['teams']['away']['name']}"
    fixture_options[key] = f

selected_label = st.selectbox("Choisis un match :", list(fixture_options.keys()))
selected_fixture = fixture_options[selected_label]

home_id = selected_fixture['teams']['home']['id']
away_id = selected_fixture['teams']['away']['id']
home_name = selected_fixture['teams']['home']['name']
away_name = selected_fixture['teams']['away']['name']
league_id = selected_fixture['league']['id']

def get_team_stats(team_id, league_id):
    for season in [2025, 2024]:
        data = api_call("teams/statistics", {"team": team_id, "league": league_id, "season": season})
        if data and data.get("response"):
            return data["response"]
    return None

if st.button("🚀 LANCER ANALYSE", type="primary", use_container_width=True):
    with st.spinner("Calcul..."):
        home_stats = get_team_stats(home_id, league_id)
        away_stats = get_team_stats(away_id, league_id)
        if not home_stats or not away_stats:
            st.warning("Stats non dispo, choisis Top 5 championnats.")
            st.stop()
        home_goals_avg = float(home_stats['goals']['for']['average']['total'] or 1.2)
        away_goals_avg = float(away_stats['goals']['for']['average']['total'] or 1.2)
        home_conceded_avg = float(home_stats['goals']['against']['average']['total'] or 1.1)
        away_conceded_avg = float(away_stats['goals']['against']['average']['total'] or 1.1)
        btts_score = 0
        if home_goals_avg >= 1.2: btts_score += 20
        if away_goals_avg >= 1.2: btts_score += 20
        if home_conceded_avg >= 0.9: btts_score += 15
        if away_conceded_avg >= 0.9: btts_score += 15
        if home_stats['clean_sheet']['total'] < 8: btts_score += 15
        if away_stats['clean_sheet']['total'] < 8: btts_score += 15
        btts_score = min(btts_score, 95)
        total_attack = home_goals_avg + away_goals_avg + home_conceded_avg + away_conceded_avg
        over25_score = int((total_attack / 3.2) * 100)
        over25_score = min(max(over25_score, 25), 90)
        corner_score = int(total_attack * 2.2 + 2)
        corner_score = min(max(corner_score, 6), 13)
        action_score = int((btts_score * 0.4) + (over25_score * 0.4) + (corner_score * 2))
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("BTTS", f"{btts_score}%")
    col2.metric("OVER 2.5", f"{over25_score}%")
    col3.metric("CORNERS", f"~{corner_score}")
    col4.metric("ACTION", f"{action_score}/100")
    if btts_score >= 75:
        st.success(f"✅ BTTS FORT {btts_score}%")
    elif btts_score >= 60:
        st.warning(f"⚠️ BTTS MOYEN {btts_score}%")
    else:
        st.error(f"❌ PAS BTTS {btts_score}%")

st.caption(f"Analyse {datetime.now().strftime('%H:%M')} GMT")
