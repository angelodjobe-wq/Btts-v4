import os
import streamlit as st
import requests
from datetime import datetime
import pytz

st.set_page_config(page_title="ANGELO V7 AUTO", layout="wide", page_icon="⚽")

API_KEY = os.getenv("API_FOOTBALL_KEY") or ""
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

def api_call(endpoint, params):
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
        return r.json()
    except:
        return None

# DATE AUTO ABIDJAN - ÇA MONTE TOUT SEUL CHAQUE JOUR
tz_abidjan = pytz.timezone("Africa/Abidjan")
today = datetime.now(tz_abidjan)
date_str = today.strftime("%Y-%m-%d")

st.title("⚽ ANGELO V7 - AUTO DAILY")
st.caption(f"Matchs du Jour Auto | {today.strftime('%d.%m.%Y')} Abidjan | Ça monte chaque jour")
st.divider()

# On récupère TOUS les matchs du jour auto
fixtures_data = api_call("fixtures", {"date": date_str, "timezone": "Africa/Abidjan"})

if not fixtures_data or not fixtures_data.get("response"):
    st.warning(f"Aucun match le {date_str} ou API en pause")
    st.stop()

fixtures = fixtures_data["response"]
# Tri par heure - ça monte dans l'ordre
fixtures = sorted(fixtures, key=lambda x: x['fixture']['date'])

# On garde seulement les matchs à venir (pas finis)
fixtures_upcoming = [f for f in fixtures if f['fixture']['status']['short'] in ["NS", "TBD"]]

st.subheader(f"📅 {len(fixtures_upcoming)} Matchs Aujourd'hui - {date_str}")
st.caption("La liste se met à jour automatiquement chaque jour à 00h00 Abidjan")

# Recherche rapide
search = st.text_input("🔍 Cherche une équipe (ex: Roma, Lazio)", "")
if search:
    fixtures_upcoming = [f for f in fixtures_upcoming if search.lower() in f['teams']['home']['name'].lower() or search.lower() in f['teams']['away']['name'].lower()]

fixture_options = {}
for f in fixtures_upcoming:
    heure = f['fixture']['date'][11:16]
    key = f"{heure} - {f['teams']['home']['name']} vs {f['teams']['away']['name']} ({f['league']['name']})"
    fixture_options[key] = f

if not fixture_options:
    st.info("Aucun match avec ce nom")
    st.stop()

selected_label = st.selectbox(f"Choisis un match ({len(fixture_options)} dispo) :", list(fixture_options.keys()))
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
    with st.spinner("Analyse..."):
        hs = get_team_stats(home_id, league_id)
        aws = get_team_stats(away_id, league_id)
        if not hs or not aws:
            st.warning("Stats non dispo pour cette petite ligue")
            st.stop()
        hg = float(hs['goals']['for']['average']['total'] or 1.2)
        ag = float(aws['goals']['for']['average']['total'] or 1.2)
        hc = float(hs['goals']['against']['average']['total'] or 1.1)
        ac = float(aws['goals']['against']['average']['total'] or 1.1)
        btts = 0
        if hg>=1.2: btts+=20
        if ag>=1.2: btts+=20
        if hc>=0.9: btts+=15
        if ac>=0.9: btts+=15
        if hs['clean_sheet']['total']<8: btts+=15
        if aws['clean_sheet']['total']<8: btts+=15
        btts=min(btts,95)
        total = hg+ag+hc+ac
        over25 = min(max(int((total/3.2)*100),25),90)
        corner = min(max(int(total*2.2+2),6),13)
        action = int((btts*0.4)+(over25*0.4)+(corner*2))
    
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("BTTS", f"{btts}%", "FORT" if btts>=75 else "MOYEN")
    c2.metric("OVER 2.5", f"{over25}%")
    c3.metric("CORNERS", f"~{corner}")
    c4.metric("ACTION", f"{action}/100")
    
    if btts>=75: st.success(f"✅ BTTS FORT {home_name} vs {away_name} {btts}%")
    elif btts>=60: st.warning(f"⚠️ BTTS MOYEN {btts}%")
    else: st.error(f"❌ PAS BTTS {btts}%")
    
    st.progress(btts/100)

st.caption(f"Auto Daily {today.strftime('%H:%M')} Abidjan | Chaque jour ça monte")
