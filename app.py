import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
import requests
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)

API_KEY = os.getenv("API_FOOTBALL_KEY")
API_HOST = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY} if API_KEY else {}

# Cache simple pour respecter le quota API (100 req/jour en gratuit)
CACHE = {}  # key -> (timestamp, data)
CACHE_TTL = 12 * 3600  # 12h
LAST_CALL = 0

def api_call(endpoint, params):
    global LAST_CALL
    if not API_KEY:
        return None, "API_FOOTBALL_KEY manquante"
    
    cache_key = f"{endpoint}:{str(params)}"
    if cache_key in CACHE:
        ts, data = CACHE[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data, None

    # Respect rate limit gratuit: ~2 req/sec max
    elapsed = time.time() - LAST_CALL
    if elapsed < 0.4:
        time.sleep(0.4 - elapsed)
    LAST_CALL = time.time()

    try:
        r = requests.get(f"{API_HOST}/{endpoint}", headers=HEADERS, params=params, timeout=15)
        if r.status_code != 200:
            return None, f"API {r.status_code}: {r.text[:200]}"
        data = r.json()
        if data.get("errors") and any(data["errors"].values()):
            return None, f"Erreur API: {data['errors']}"
        CACHE[cache_key] = (time.time(), data)
        return data, None
    except Exception as e:
        return None, str(e)

def get_today_fixtures():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data, err = api_call("fixtures", {"date": today})
    if err:
        return None, err
    return data.get("response", []), None

def get_last_team_fixtures(team_id, last_n=10):
    # On récupère les 10 derniers matchs terminés
    data, err = api_call("fixtures", {"team": team_id, "last": last_n, "status": "FT"})
    if err:
        return None, err
    return data.get("response", []), None

def analyze_team(fixtures, is_home_context=True):
    """Calcule stats BTTS, buts marqués/encaissés"""
    if not fixtures:
        return None
    
    stats = {
        "total": len(fixtures),
        "btts_count": 0,
        "scored": 0,
        "conceded": 0,
        "home_games": 0,
        "away_games": 0,
        "scored_home": 0,
        "conceded_home": 0,
        "scored_away": 0,
        "conceded_away": 0,
        "btts_home": 0,
        "btts_away": 0,
    }
    
    for f in fixtures:
        team_id = f["teams"]["home"]["id"] if is_home_context else f["teams"]["away"]["id"]
        # On doit savoir si notre équipe était à domicile dans ce match historique
        was_home = f["teams"]["home"]["id"] == fixtures[0]["teams"]["home"]["id"] if fixtures else True
        # En fait on déduit à chaque match
        # Simplification: on passe l'id de l'équipe à analyser
        # CORRECTION: on va le faire proprement dans la boucle appelante

    return stats

def analyze_team_by_id(fixtures, target_team_id):
    total = len(fixtures)
    if total == 0:
        return None
    btts = 0
    scored = 0
    conceded = 0
    scored_home = conceded_home = 0
    scored_away = conceded_away = 0
    btts_home = btts_away = 0
    home_games = away_games = 0
    no_score = 0

    for fx in fixtures:
        goals = fx.get("goals", {})
        if goals["home"] is None or goals["away"] is None:
            continue
        gh = goals["home"]
        ga = goals["away"]
        is_home = fx["teams"]["home"]["id"] == target_team_id
        
        if is_home:
            home_games += 1
            scored_home += gh
            conceded_home += ga
            if gh > 0 and ga > 0:
                btts_home += 1
                btts += 1
            if gh == 0:
                no_score += 1
        else:
            away_games += 1
            scored_away += ga
            conceded_away += gh
            if gh > 0 and ga > 0:
                btts_away += 1
                btts += 1
            if ga == 0:
                no_score += 1
        
        scored += gh if is_home else ga
        conceded += ga if is_home else gh
        if gh > 0 and ga > 0:
            pass # déjà compté
        elif not is_home:
            # éviter double comptage btts
            if gh > 0 and ga > 0 and not is_home:
                pass

    # Re-calcul btts total correct
    btts = btts_home + btts_away
    
    def safe_div(a,b): return a / b if b else 0

    return {
        "total": total,
        "home_games": home_games,
        "away_games": away_games,
        "btts_count": btts,
        "btts_pct": safe_div(btts, total) * 100,
        "btts_home_pct": safe_div(btts_home, home_games) * 100 if home_games else None,
        "btts_away_pct": safe_div(btts_away, away_games) * 100 if away_games else None,
        "avg_scored": safe_div(scored, total),
        "avg_conceded": safe_div(conceded, total),
        "avg_scored_home": safe_div(scored_home, home_games),
        "avg_conceded_home": safe_div(conceded_home, home_games),
        "avg_scored_away": safe_div(scored_away, away_games),
        "avg_conceded_away": safe_div(conceded_away, away_games),
        "clean_sheet_fail_pct_home": safe_div(home_games - sum(1 for f in fixtures if f["teams"]["home"]["id"]==target_team_id and f["goals"]["away"]==0), home_games)*100 if home_games else None,
        "details": fixtures
    }

def estimate_btts_prob(home_stats, away_stats):
    """
    Méthode statistique explicite (sans garantie):
    1. P(Home marque) = moyenne entre:
       - % matchs où Home a marqué à domicile
       - % matchs où Away a encaissé à l'extérieur
    2. P(Away marque) = moyenne entre:
       - % matchs où Away a marqué à l'extérieur
       - % matchs où Home a encaissé à domicile
    3. P(BTTS) = P(Home marque) * P(Away marque)  (hypothèse d'indépendance)
    
    Limite: l'indépendance est fausse en foot, c'est une estimation.
    On lisse avec la moyenne BTTS globale des 2 équipes.
    """
    if not home_stats or not away_stats:
        return None, "Données manquantes"

    def score_rate_home(h):
        if h["home_games"] == 0: return None
        scored_games = sum(1 for f in h["details"] if f["teams"]["home"]["id"]==h["details"][0]["teams"]["home"]["id"] or True) # simplifié
        # Calcul précis: % matchs où a marqué
        count = 0
        for f in h["details"]:
            is_home = f["teams"]["home"]["id"] == f["teams"]["home"]["id"] if True else False
            # on utilise les stats déjà calculées
        # On utilise avg > 0 comme proxy
        # Plus robuste: on recalcule
        total_home = h["home_games"]
        if total_home == 0: return 0.6
        # estimation: si avg_scored_home >0.8, proba haute
        return min(0.95, max(0.15, h["avg_scored_home"] / 1.8 + 0.25))

    # Version simple et transparente:
    p_home_scores_home = (home_stats["avg_scored_home"] > 0)
    # Calcul réel: fréquence où l'équipe a marqué
    def freq_scored(stats, at_home):
        games = [f for f in stats["details"] if (f["teams"]["home"]["id"]==stats["details"][0]["teams"]["home"]["id"] if False else True)]
        # On refait proprement
        c = 0
        tot = 0
        for f in stats["details"]:
            tid = stats["details"][0]["teams"]["home"]["id"] # placeholder, on va passer le bon id dans l'appel
            # Cette fonction sera appelée avec les bons filtres ci-dessous
        return 0

    # Implémentation directe et lisible:
    def calc_scoring_freq(fixtures, team_id, home_only=False, away_only=False):
        if not fixtures: return None
        scored = 0
        total = 0
        for f in fixtures:
            is_home = f["teams"]["home"]["id"] == team_id
            if home_only and not is_home: continue
            if away_only and is_home: continue
            total += 1
            g = f["goals"]["home"] if is_home else f["goals"]["away"]
            if g and g > 0:
                scored += 1
        return scored / total if total else None

    # On récupère les team_id depuis les stats
    home_team_id = home_stats["details"][0]["teams"]["home"]["id"] if home_stats["details"] and home_stats["details"][0]["teams"]["home"]["id"] in [f["teams"]["home"]["id"] for f in home_stats["details"]] else None
    # En pratique on a besoin de passer les ids, on les récupère autrement dans l'analyse globale

    # Pour simplifier et rester explicite, on utilise les moyennes déjà calculées avec formule transparente:
    # P marque = 0.5 * (freq marque) + 0.5 * (freq encaisse adversaire)
    
    # Ces valeurs seront calculées dans analyze_match() où on a les ids
    
    return None, "Calculé dans analyze_match"

def analyze_match(fixture):
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    
    home_last, err1 = get_last_team_fixtures(home_id, 10)
    away_last, err2 = get_last_team_fixtures(away_id, 10)
    
    if err1 or err2:
        return {"error": err1 or err2, "fixture": fixture}
    
    hs = analyze_team_by_id(home_last, home_id)
    aw = analyze_team_by_id(away_last, away_id)
    
    if not hs or not aw or hs["total"] < 3 or aw["total"] < 3:
        return {
            "fixture": fixture,
            "home_stats": hs,
            "away_stats": aw,
            "prob": None,
            "reason": "Données insuffisantes (<3 matchs)",
            "confidence": "faible"
        }
    
    def freq_score(fixtures, team_id, location=None):
        tot = 0
        scored = 0
        for f in fixtures:
            is_home = f["teams"]["home"]["id"] == team_id
            if location == "home" and not is_home: continue
            if location == "away" and is_home: continue
            tot += 1
            g = f["goals"]["home"] if is_home else f["goals"]["away"]
            if g is not None and g > 0:
                scored += 1
        return scored / tot if tot else 0.5, tot

    def freq_concede(fixtures, team_id, location=None):
        tot = 0
        conceded = 0
        for f in fixtures:
            is_home = f["teams"]["home"]["id"] == team_id
            if location == "home" and not is_home: continue
            if location == "away" and is_home: continue
            tot += 1
            g = f["goals"]["away"] if is_home else f["goals"]["home"]
            if g is not None and g > 0:
                conceded += 1
        return conceded / tot if tot else 0.5, tot

    p_home_scores_freq, _ = freq_score(home_last, home_id, "home")
    p_away_concedes_away, _ = freq_concede(away_last, away_id, "away")
    p_away_scores_freq, _ = freq_score(away_last, away_id, "away")
    p_home_concedes_home, _ = freq_concede(home_last, home_id, "home")

    # Estimation finale explicite
    p_home_to_score = (p_home_scores_freq + p_away_concedes_away) / 2
    p_away_to_score = (p_away_scores_freq + p_home_concedes_home) / 2
    
    # Lissage avec BTTS historique moyen
    avg_btts_hist = (hs["btts_pct"] + aw["btts_pct"]) / 200  # en proba 0-1
    
    prob_btts = (p_home_to_score * p_away_to_score * 0.7) + (avg_btts_hist * 0.3)
    prob_btts = max(0.05, min(0.95, prob_btts))

    confidence = "élevée" if hs["total"]>=8 and aw["total"]>=8 else "moyenne" if hs["total"]>=5 else "faible"

    return {
        "fixture": fixture,
        "home_stats": hs,
        "away_stats": aw,
        "calc": {
            "p_home_scores_home": p_home_scores_freq,
            "p_away_concedes_away": p_away_concedes_away,
            "p_home_to_score": p_home_to_score,
            "p_away_scores_away": p_away_scores_freq,
            "p_home_concedes_home": p_home_concedes_home,
            "p_away_to_score": p_away_to_score,
            "avg_btts_hist": avg_btts_hist,
            "formule": "P(BTTS) = 0.7*P(HomeScore)*P(AwayScore) + 0.3*AvgBTTS_Hist | P(HomeScore)=(FreqHomeScoreHome+FreqAwayConcedeAway)/2"
        },
        "prob": prob_btts,
        "prob_pct": round(prob_btts*100, 1),
        "confidence": confidence,
        "missing": []
    }

HTML = """
<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTTS V4 - Analyse</title>
<style>
body{font-family:system-ui;background:#0f1115;color:#e6e6e6;padding:16px}
.card{background:#1a1e27;border-radius:12px;padding:14px;margin:12px 0;border:1px solid #2a2f3d}
.btn{background:#ff3b3b;color:white;padding:10px 18px;border:none;border-radius:8px;cursor:pointer;font-weight:bold}
.btn:disabled{opacity:.5}
.green{background:#1f3d2b;color:#7CFC9A;padding:8px;border-radius:8px}
.yellow{background:#3d3520;color:#ffda6b;padding:8px;border-radius:8px}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:8px;border-bottom:1px solid #2a2f3d;text-align:left;font-size:14px}
.top3{border:2px solid #ffda6b}
small{color:#9aa0b2}
</style>
</head>
<body>
<h2>BTTS V4 - Marchés prévus pour les prochaines versions</h2>
<p><small>BTTS • Plus/Moins • Double chance • Corners • Cartons si disponibles</small></p>
<div class="yellow">Cette version affiche les rencontres. Elle ne fournit pas encore de prédictions validées : les marchés seront ajoutés puis testés progressivement. Aucune garantie.</div>

<div style="margin:16px 0">
<button class="btn" onclick="loadMatches()">Charger les matchs</button>
<button class="btn" id="analyzeBtn" onclick="analyzeTop()" style="background:#2e7bff;margin-left:8px">Analyser BTTS (Top 15)</button>
<input id="maxInput" type="number" value="15" min="3" max="20" style="width:60px;margin-left:8px;padding:6px;border-radius:6px"> <small>max à analyser (limite API)</small>
</div>

<div id="status"></div>
<div id="results"></div>
<div id="analysis"></div>

<script>
let allMatches = [];
async function loadMatches(){
 document.getElementById('status').innerHTML='Chargement...';
 let r = await fetch('/api/fixtures'); let j = await r.json();
 if(j.error){ document.getElementById('status').innerHTML='<div class="card" style="color:#ff6b6b">'+j.error+'</div>'; return; }
 allMatches = j.fixtures;
 document.getElementById('status').innerHTML='<div class="green">'+j.fixtures.length+' match(s) récupéré(s).</div>';
 let html='<table><tr><th>Heure (UTC)</th><th>Championnat</th><th>Match</th></tr>';
 j.fixtures.forEach(f=>{
   html+=`<tr><td>${new Date(f.fixture.date).toISOString().substr(11,5)}</td><td>${f.league.name}</td><td>${f.teams.home.name} vs ${f.teams.away.name}</td></tr>`;
 });
 html+='</table>';
 document.getElementById('results').innerHTML=html;
}

async function analyzeTop(){
 if(allMatches.length==0){ alert('Charge d\'abord les matchs'); return; }
 let max = parseInt(document.getElementById('maxInput').value) || 15;
 if(max>20){ max=20; alert('Limité à 20 pour respecter le quota API gratuit (100 req/jour)'); }
 document.getElementById('analysis').innerHTML='<div class="card">Analyse en cours... 1 appel = 2 équipes. '+max+' matchs = ~'+(max*2)+' requêtes. Patiente 30-60s...</div>';
 document.getElementById('analyzeBtn').disabled=true;
 let r = await fetch('/api/analyze?max='+max); let j = await r.json();
 document.getElementById('analyzeBtn').disabled=false;
 if(j.error){ document.getElementById('analysis').innerHTML='<div class="card" style="color:#ff6b6b">'+j.error+'</div>'; return; }
 
 let html='<h3>Top 3 candidats BTTS (estimation, pas garantie)</h3><small>Méthode: P(BTTS)=0.7*P(HomeScore)*P(AwayScore)+0.3*AvgBTTS_hist. Limite: hypothèse d\'indépendance fausse, échantillon 5-10 matchs seulement.</small>';
 if(j.top3.length==0){ html+='<div class="card">Pas assez de données</div>'; }
 j.top3.forEach((a,i)=>{
   let f = a.fixture;
   html+=`<div class="card top3"><b>#${i+1} ${f.teams.home.name} vs ${f.teams.away.name}</b> - ${f.league.name}<br>
   <b>Prob estimée BTTS: ${a.prob_pct}%</b> (confiance: ${a.confidence})<br>
   <small>Formule: ${a.calc.formule}</small><br>
   <table><tr><th></th><th>Domicile (${f.teams.home.name})</th><th>Extérieur (${f.teams.away.name})</th></tr>
   <tr><td>BTTS % (10 derniers)</td><td>${a.home_stats.btts_pct.toFixed(1)}% sur ${a.home_stats.total} matchs</td><td>${a.away_stats.btts_pct.toFixed(1)}% sur ${a.away_stats.total} matchs</td></tr>
   <tr><td>BTTS domicile/extérieur</td><td>${a.home_stats.btts_home_pct!==null?a.home_stats.btts_home_pct.toFixed(1)+'% à domicile':'N/A'}</td><td>${a.away_stats.btts_away_pct!==null?a.away_stats.btts_away_pct.toFixed(1)+'% à l\'extérieur':'N/A'}</td></tr>
   <tr><td>Buts marqués/encaissés (moy)</td><td>${a.home_stats.avg_scored_home.toFixed(2)} / ${a.home_stats.avg_conceded_home.toFixed(2)} à domicile</td><td>${a.away_stats.avg_scored_away.toFixed(2)} / ${a.away_stats.avg_conceded_away.toFixed(2)} à l'extérieur</td></tr>
   <tr><td>P(Home marque) / P(Away marque)</td><td colspan="2">${(a.calc.p_home_to_score*100).toFixed(1)}% / ${(a.calc.p_away_to_score*100).toFixed(1)}% (moyenne freq score + freq encaisse adverse)</td></tr>
   </table>
   <small>Données manquantes: ${a.missing.length? a.missing.join(', ') : 'aucune majeure, mais seulement 5-10 matchs utilisés'}<br>Limites: petit échantillon, pas de prise en compte blessures, motivation, météo. Estimation, jamais garantie.</small>
   </div>`;
 });
 html+='<h4>Tous les matchs analysés</h4><table><tr><th>Match</th><th>Prob</th><th>Confiance</th><th>Raison</th></tr>';
 j.all.forEach(a=>{
   html+=`<tr><td>${a.fixture.teams.home.name} vs ${a.fixture.teams.away.name}</td><td>${a.prob_pct!==undefined?a.prob_pct+'%':'-'}</td><td>${a.confidence||''}</td><td><small>${a.reason||''}</small></td></tr>`;
 });
 html+='</table><div class="yellow" style="margin-top:12px">Quota API: ${j.quota_used} appels, cache: ${j.cache_size} entrées. Respecte limite 100/jour en gratuit.</div>';
 document.getElementById('analysis').innerHTML=html;
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/fixtures")
def api_fixtures():
    fixtures, err = get_today_fixtures()
    if err:
        return jsonify({"error": err}), 500
    # Tri par heure
    fixtures = sorted(fixtures, key=lambda x: x["fixture"]["date"])
    return jsonify({"fixtures": fixtures, "count": len(fixtures)})

@app.route("/api/analyze")
def api_analyze():
    max_analyze = int(request.args.get("max", 15))
    max_analyze = min(max_analyze, 20)  # protection quota
    fixtures, err = get_today_fixtures()
    if err:
        return jsonify({"error": err}), 500
    fixtures = sorted(fixtures, key=lambda x: x["fixture"]["date"])[:max_analyze]
    
    results = []
    for fx in fixtures:
        res = analyze_match(fx)
        results.append(res)
    
    # Filtrer ceux avec prob
    with_prob = [r for r in results if r.get("prob") is not None]
    with_prob_sorted = sorted(with_prob, key=lambda x: x["prob"], reverse=True)
    top3 = with_prob_sorted[:3]

    return jsonify({
        "all": with_prob_sorted + [r for r in results if r.get("prob") is None],
        "top3": top3,
        "quota_used": len(CACHE),
        "cache_size": len(CACHE),
        "method": "P(HomeScore)=(FreqScoreHomeDomicile+FreqConcedeAwayExterieur)/2, P(AwayScore)=(FreqScoreAwayExterieur+FreqConcedeHomeDomicile)/2, P(BTTS)=0.7*P_H*P_A+0.3*AvgBTTS_Hist"
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port) 
