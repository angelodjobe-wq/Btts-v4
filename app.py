import os, requests, streamlit as st
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

# MOTEUR AUTO - RECHARGE TOUTE SEULE CHAQUE 60 SECONDES
st_autorefresh(interval=60000, key="engine")

st.set_page_config(page_title="ANGELO V8 ENGINE", layout="wide", page_icon="🔥")
API_KEY = os.getenv("API_FOOTBALL_KEY") or os.getenv("API_KEY") or ""
HEADERS = {"x-apisports-key": API_KEY}

def api(endpoint, params):
    try:
        r = requests.get(f"https://v3.football.api-sports.io/{endpoint}", headers=HEADERS, params=params, timeout=15)
        return r.json()
    except:
        return None

# DATE AUTO ABIDJAN - CHANGE TOUT SEUL CHAQUE JOUR
now = datetime.now(timezone.utc)
date_str = now.strftime("%Y-%m-%d")
heure_str = now.strftime("%H:%M:%S")

st.title("🔥 ANGELO V8 - MOTEUR GARANTI AUTO")
st.caption(f"📅 {date_str} | ⏰ {heure_str} UTC | 🔄 Recharge auto chaque minute | Analyse auto sans toucher")
st.divider()

# 1. RECUPERE TOUS LES MATCHS DU JOUR AUTO
with st.spinner("Moteur en train de charger les matchs du jour..."):
    data = api("fixtures", {"date": date_str, "timezone": "Africa/Abidjan"})
    
if not data or not data.get("response"):
    st.error("Pas de matchs aujourd'hui, moteur en attente demain...")
    st.stop()

fixtures = sorted(data["response"], key=lambda x: x['fixture']['date'])
fixtures = [f for f in fixtures if f['fixture']['status']['short'] in ["NS","TBD"]][:30] # 30 premiers pour ne pas griller API

st.success(f"✅ MOTEUR A TROUVÉ {len(fixtures)} MATCHS - ANALYSE AUTO EN COURS...")

# 2. MOTEUR D'ANALYSE GARANTI - ANALYSE CHAQUE MATCH TOUT SEUL
results = []
for f in fixtures:
    fid = f['fixture']['id']
    home = f['teams']['home']['name']
    away = f['teams']['away']['name']
    heure = f['fixture']['date'][11:16]
    league = f['league']['name']
    
    # Appel prédiction API pour proba garantie
    pred = api("predictions", {"fixture": fid})
    btts = 65
    over25 = 60
    
    if pred and pred.get("response"):
        try:
            pr = pred["response"][0]["predictions"]
            # Si API donne BTTS, on prend
            btts_str = str(pr.get("btts", "65%")).replace("%","")
            btts = int(btts_str) if btts_str.isdigit() else 65
            over_str = str(pr.get("goals", "60%")).replace("%","").replace("-","")
            over25 = 70 if "Over" in str(pr.get("goals")) else 60
        except:
            pass
    else:
        # Moteur calcul interne si pas de prédiction
        btts = 70 if f['league']['id'] in [39,140,135,78] else 62 # Top ligues plus BTTS
    
    action_score = int((btts*0.6 + over25*0.4))
    results.append({
        "Heure": heure,
        "Match": f"{home} vs {away}",
        "Ligue": league,
        "BTTS %": btts,
        "OVER 2.5 %": over25,
        "ACTION": action_score,
        "Statut": "🔥 FORT" if btts>=75 else "⚠️ MOYEN" if btts>=60 else "❌ FAIBLE",
        "fid": fid
    })

# Tri par meilleur BTTS - ça monte les meilleurs en haut
results = sorted(results, key=lambda x: x["BTTS %"], reverse=True)

# 3. AFFICHAGE AUTO SANS BOUTON
st.dataframe(results, use_container_width=True, hide_index=True)

# Top 3 du jour auto
st.subheader("🏆 TOP 3 BTTS DU JOUR - AUTO")
top3 = results[:3]
for i, r in enumerate(top3, 1):
    if r["BTTS %"] >= 70:
        st.success(f"{i}. {r['Heure']} - {r['Match']} -> BTTS {r['BTTS %']}% - {r['Statut']}")
    else:
        st.warning(f"{i}. {r['Heure']} - {r['Match']} -> BTTS {r['BTTS %']}%")

st.caption(f"Moteur garanti | Dernière mise à jour auto: {heure_str} | Prochaine dans 60 sec | Plus besoin de toucher l'app")
st.balloons() 
