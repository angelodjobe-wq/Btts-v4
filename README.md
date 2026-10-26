# BTTS V4

Application Streamlit de départ pour récupérer les matchs du jour avec API-Football.

## Lancer en local
1. Installer Python 3.10 ou plus récent.
2. Installer les dépendances : `pip install -r requirements.txt`
3. Définir la variable d'environnement `API_FOOTBALL_KEY` avec votre clé API-Football.
4. Lancer : `streamlit run app.py`

## Sécurité
Ne mettez jamais la clé API dans `app.py`, `README.md` ou dans un dépôt GitHub public. Configurez-la dans les secrets de la plateforme d'hébergement.

## État actuel
Cette version récupère et affiche les rencontres. Les prédictions BTTS, buts, vainqueur/double chance, corners et cartons sont prévues pour des étapes suivantes. Toute probabilité sera une estimation, pas une garantie.
