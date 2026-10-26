import os
from datetime import date, timedelta
import time
import requests
import streamlit as st

st.set_page_config(page_title="BTTS V4 - Analyse", layout="wide")
st.title("⚽ BTTS V4 - Analyse")
st.caption("Version avec moteur BTTS - Estimation statistique, aucune garantie")

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

if not API_KEY:
    st.error("❌ Clé API manquante ! Va dans Render > Environment > API_FOOTBALL_KEY")
    st.stop()

HEADERS = {"x-apisports-key": API_KEY}

# Cache + rate limit pour quota gratuit 100 req/jour
if "cache" not in st.session_state:
    st.session_state.cache = {}
if "last_call" not in st.session_state:
    st.session_state.last_call = 0

def api_call(endpoint, params):
    key = f"{endpoint}:{params}"
    # cache 12h
    if key in st.session_state.cache:
        ts, data = st.session_state.cache[key]
        if time.time() - ts < 43200:
            return data, None
    
    elapsed = time.time() - st.session_state.last_call
    if elapsed < 0.4:
        time.sleep(0.4 - elapsed)
    st.session_state.last_call = time.time()

    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=15)
        if r.status_code != 200:
            return None, f"API {r.status_code}"
        j = r.json()
        if j.get("errors") and any(j["errors"].values()):
            return None, str(j["errors"])
        st.session_state.cache[key] = (time.time(), j)
        return j, None
    except Exception as e:
        return None, str(e)

def fetch_fixtures(day):
    if not API_KEY:
        return None, "Clé API absente"
    data, err = api_call("fixtures", {"date": str(day)})
    if err:
        return None, err
    return data.get("response", []), None

def fetch_last_team(team_id, last_n=10):
    data, err = api_call("fixtures", {"team": team_id, "last": last_n, "status": "FT"})
    if err:
        return None, err
    return data.get("response", []), None

def analyze_team(fixtures, team_id):
    if not fixtures:
        return None
    home_games = away_games = 0
    btts_h = btts_a = 0
    sc_h = co_h = sc_a = co_a = 0
    
    for f in fixtures:
        g = f.get("goals", {})
        if g["home"] is None or g["away"] is None:
            continue
        is_home = f["teams"]["home"]["id"] == team_id
        gh, ga = g["home"], g["away"]
        if is_home:
            home_games+=1
            sc_h+=gh; co_h+=ga
            if gh>0 and ga>0: btts_h+=1
        else:
            away_games+=1
            sc_a+=ga; co_a+=gh
            if gh>0 and ga>0: btts_a+=1
    
    total = home_games+away_games
    def sd(a,b): return a/b if b else 0
    return {
        "total": total, "home_games": home_games, "away_games": away_games,
        "btts": btts_h+btts_a, "btts_pct": sd(btts_h+btts_a,total)*100,
        "btts_home_pct": sd(btts_h,home_games)*100 if home_games else None,
        "btts_away_pct": sd(btts_a,away_games)*100 if away_games else None,
        "avg_sc_h": sd(sc_h,home_games), "avg_co_h": sd(co_h,home_games),
        "avg_sc_a": sd(sc_a,away_games), "avg_co_a": sd(co_a,away_games),
        "details": fixtures
    }

def analyze_match(fixture):
    hid = fixture["teams"]["home"]["id"]
    aid = fixture["teams"]["away"]["id"]
    h_last, e1 = fetch_last_team(hid, 10)
    a_last, e2 = fetch_last_team(aid, 10)
    if e1 or e2:
        return {"fixture": fixture, "error": e1 or e2}
    hs = analyze_team(h_last, hid)
    aw = analyze_team(a_last, aid)
    if not hs or not aw or hs["total"]<3 or aw["total"]<3:
        return {"fixture": fixture, "home_stats": hs, "away_stats": aw, "prob": None, "reason": f"Données insuffisantes ({hs['total'] if hs else 0}/{aw['total'] if aw else 0})", "confidence":"faible"}

    def freq_score(fxs, tid, loc=None):
        t=s=0
        for f in fxs:
            is_h = f["teams"]["home"]["id"]==tid
            if loc=="home" and not is_h: continue
            if loc=="away" and is_h: continue
            t+=1
            g = f["goals"]["home"] if is_h else f["goals"]["away"]
            if g and g>0: s+=1
        return s/t if t else 0.5
    def freq_conc(fxs, tid, loc=None):
        t=c=0
        for f in fxs:
            is_h = f["teams"]["home"]["id"]==tid
            if loc=="home" and not is_h: continue
            if loc=="away" and is_h: continue
            t+=1
            g = f["goals"]["away"] if is_h else f["goals"]["home"]
            if g and g>0: c+=1
        return c/t if t else 0.5

    p_h_sc = freq_score(h_last, hid, "home")
    p_a_co = freq_conc(a_last, aid, "away")
    p_a_sc = freq_score(a_last, aid, "away")
    p_h_co = freq_conc(h_last, hid, "home")

    p_home = (p_h_sc + p_a_co)/2
    p_away = (p_a_sc + p_h_co)/2
    avg_btts = (hs["btts_pct"]+aw["btts_pct"])/200
    prob = (p_home*p_away*0.7)+(avg_btts*0.3)
    prob = max(0.05,min(0.95,prob))
    conf = "élevée" if hs["total"]>=8 and aw["total"]>=8 else "moyenne" if hs["total"]>=5 else "faible"
    return {
        "fixture": fixture, "home_stats": hs, "away_stats": aw,
        "calc": {"p_h_sc": p_h_sc, "p_a_co": p_a_co, "p_home": p_home, "p_a_sc": p_a_sc, "p_h_co": p_h_co, "p_away": p_away, "avg_btts": avg_btts,
                 "formule": "P(H)=(FreqScoreDom+FreqEncaisseExtAdv)/2, P(A)=(FreqScoreExt+FreqEncaisseDomAdv)/2, P(BTTS)=0.7*P(H)*P(A)+0.3*AvgBTTS_hist"},
        "prob": prob, "prob_pct": round(prob*100,1), "confidence": conf
    }

# --- INTERFACE ORIGINALE CONSERVÉE ---
today = date.today()
fixtures, err = fetch_fixtures(today)

if err:
    st.error(err)
    st.stop()

st.success(f"{len(fixtures)} match(s) récupéré(s) pour {today}")

if fixtures:
    for f in fixtures[:30]:
        st.write(f"{f['fixture']['date'][11:16]} - {f['league']['name']} - {f['teams']['home']['name']} vs {f['teams']['away']['name']}")

st.divider()
st.subheader("Moteur BTTS - Top 3 candidats (estimation)")

st.warning("Méthode: P(BTTS)=0.7*P(HomeScore)*P(AwayScore)+0.3*AvgBTTS_hist. Limites: hypothèse d'indépendance fausse, seulement 5-10 derniers matchs, pas de blessures/météo. Jamais garantie.")

max_analyse = st.slider("Nombre de matchs à analyser (limite quota gratuit)", 3, 20, 10, help="10 matchs = 20 requêtes API. Gratuit = 100/jour max. Cache 12h actif.")
if st.button("🔍 Analyser BTTS"):
    if len(fixtures)==0:
        st.error("Pas de matchs aujourd'hui")
        st.stop()
    to_analyse = sorted(fixtures, key=lambda x: x["fixture"]["date"])[:max_analyse]
    results = []
    bar = st.progress(0)
    for i, fx in enumerate(to_analyse):
        bar.progress((i+1)/len(to_analyse), text=f"Analyse {fx['teams']['home']['name']} vs {fx['teams']['away']['name']}...")
        results.append(analyze_match(fx))
    
    with_prob = [r for r in results if r.get("prob") is not None]
    top3 = sorted(with_prob, key=lambda x: x["prob"], reverse=True)[:3]

    st.subheader(f"🏆 Top 3 sur {max_analyse} analysés")
    if not top3:
        st.info("Données insuffisantes")
    for i, a in enumerate(top3):
        f = a["fixture"]
        with st.container(border=True):
            st.markdown(f"**#{i+1} {f['teams']['home']['name']} vs {f['teams']['away']['name']}** - {f['league']['name']} - **BTTS: {a['prob_pct']}%** (confiance {a['confidence']})")
            st.caption(f"Formule: {a['calc']['formule']}")
            col1, col2 = st.columns(2)
            col1.metric(f"{f['teams']['home']['name']} - BTTS dom", f"{a['home_stats']['btts_home_pct']:.1f}%" if a['home_stats']['btts_home_pct'] is not None else "N/A", f"{a['home_stats']['home_games']} matchs dom")
            col2.metric(f"{f['teams']['away']['name']} - BTTS ext", f"{a['away_stats']['btts_away_pct']:.1f}%" if a['away_stats']['btts_away_pct'] is not None else "N/A", f"{a['away_stats']['away_games']} matchs ext")
            st.write(f"Buts moy dom: {a['home_stats']['avg_sc_h']:.2f} marqués / {a['home_stats']['avg_co_h']:.2f} encaissés | Ext: {a['away_stats']['avg_sc_a']:.2f} / {a['away_stats']['avg_co_a']:.2f}")
            st.write(f"P(Home marque)={a['calc']['p_home']*100:.1f}% | P(Away marque)={a['calc']['p_away']*100:.1f}% | Hist BTTS moyen={a['calc']['avg_btts']*100:.1f}%")
            with st.expander("Voir détails stats et limites"):
                st.json({"home": a["home_stats"], "away": a["away_stats"], "calc": a["calc"]})
                st.write("Données manquantes: seulement 10 derniers matchs, pas de compos, blessures, motivation. Estimation pas garantie.")
    
    st.divider()
    st.write("Tous les matchs analysés")
    for a in sorted(with_prob, key=lambda x: x["prob"], reverse=True):
        f = a["fixture"]
        st.write(f"{f['teams']['home']['name']} vs {f['teams']['away']['name']} : {a['prob_pct']}% - {a['confidence']}")
