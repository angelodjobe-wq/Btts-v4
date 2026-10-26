import os
from datetime import date
import requests
import streamlit as st

st.set_page_config(page_title="BTTS V4", page_icon="⚽", layout="wide")
st.title("⚽ BTTS V4 — Analyse des matchs")
st.caption("Version de départ : données de matchs + indicateurs simples. Les probabilités sont des estimations, jamais des garanties.")

API_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
BASE_URL = "https://v3.football.api-sports.io"

def fetch_fixtures(day):
    if not API_KEY:
        return None, "Clé API absente. Configurez API_FOOTBALL_KEY dans les secrets de l'hébergement."
    try:
        response = requests.get(
            f"{BASE_URL}/fixtures",
            headers={"x-apisports-key": API_KEY},
            params={"date": str(day), "timezone": "Africa/Abidjan"},
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            return None, f"Erreur API : {data['errors']}"
        return data.get("response", []), None
    except requests.RequestException as exc:
        return None, f"Impossible de récupérer les matchs : {exc}"

with st.sidebar:
    st.header("Paramètres")
    match_date = st.date_input("Date des matchs", value=date.today())
    st.info("La clé API doit être ajoutée comme variable secrète sur la plateforme d'hébergement, jamais dans ce fichier ni dans GitHub.")

if st.button("Charger les matchs", type="primary"):
    st.session_state["load"] = True

if st.session_state.get("load"):
    fixtures, error = fetch_fixtures(match_date)
    if error:
        st.error(error)
        st.markdown("**Prochaine étape :** ajouter la clé `API_FOOTBALL_KEY` dans les secrets de l'hébergement.")
    elif not fixtures:
        st.warning("Aucun match trouvé pour cette date avec les données disponibles.")
    else:
        st.success(f"{len(fixtures)} match(s) récupéré(s).")
        rows = []
        for item in fixtures:
            fixture = item.get("fixture", {})
            league = item.get("league", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})
            status = fixture.get("status", {}).get("short", "")
            rows.append({
                "Heure (UTC)": fixture.get("date", "")[11:16],
                "Championnat": league.get("name", ""),
                "Domicile": teams.get("home", {}).get("name", ""),
                "Extérieur": teams.get("away", {}).get("name", ""),
                "Statut": status,
                "Buts domicile": goals.get("home"),
                "Buts extérieur": goals.get("away"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.subheader("Marchés prévus pour les prochaines versions")
        st.write("BTTS • Plus/Moins de buts • Double chance/vainqueur • Corners • Cartons si les données sont disponibles")
        st.warning("Cette version affiche les rencontres. Elle ne fournit pas encore de prédictions validées : les marchés seront ajoutés puis testés progressivement.")
else:
    st.write("Choisissez une date puis appuyez sur **Charger les matchs**.")
    st.write("Le premier objectif est de vérifier la connexion à l'API avant d'ajouter le moteur d'analyse.")
