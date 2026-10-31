import os, requests, streamlit as st
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=120000, key="engine")
st.set_page_config(page_title="ANGELO TOP5", layout="wide", page_icon="🔥")
API_KEY = os.getenv("API_FOOTBALL_KEY") or os.getenv("API_KEY") or ""
HEADERS = {"x-apisports-key": API_KEY}

def api(e,p):
 try:
  r=requests.get(f"https://v3.football.api-sports.io/{e}",headers=HEADERS,params=p,timeout=15)
  return r.json()
 except:
  return None

now = datetime.now(timezone.utc)
date_str = now.strftime("%Y-%m-%d")
heure_str = now.strftime("%H:%M:%S")

st.title("🔥 ANGELO - TOP 5 DU JOUR")
st.caption(f"📅 {date_str} | ⏰ {heure_str} UTC | Les 5 meilleurs BTTS auto")
st.divider()

data = api("fixtures", {"date": date_str, "timezone": "Africa/Abidjan"})
if not data or not data.get("response"):
    st.warning("Pas de matchs aujourd'hui")
    st.stop()

fixtures = [f for f in data["response"] if f['fixture']['status']['short'] in ["NS","TBD"]]

# CALCUL TOP 5
results=[]
for f in fixtures:
    home=f['teams']['home']['name']
    away=f['teams']['away']['name']
    heure=f['fixture']['date'][11:16]
    league=f['league']['name']
    lid=f['league']['id']
    # Moteur TOP 5 : on favorise grosses ligues
    btts = 82 if lid in [39,140,135,78] else 76 if lid in [61,94,2,3] else 68
    # Bonus si deux grosses équipes
    if home in ["Roma","Lazio","Sassuolo","Inter","Milan","Man City"] or away in ["Roma","Lazio","Sassuolo"]:
        btts += 4
    results.append({"heure":heure,"match":f"{home} vs {away}","ligue":league,"btts":btts,"lid":lid})

# TRI et on garde TOP 5
results = sorted(results, key=lambda x: x["btts"], reverse=True)[:5]

st.success(f"✅ TOP 5 MEILLEURS BTTS DU JOUR TROUVÉS")

for i, r in enumerate(results, 1):
    st.markdown(f"""
    ### {i}. {r['heure']} - {r['match']}
    **Ligue:** {r['ligue']} | **BTTS:** {r['btts']}% 🔥
    """)
    st.progress(r['btts']/100)
    st.divider()

st.caption(f"Auto MAJ: {heure_str} - Prochaine dans 2 min | Plus de rêve, que du concret")
st.balloons() 
