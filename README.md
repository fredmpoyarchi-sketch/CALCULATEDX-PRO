# CALCULATEDX WEB

CALCULATEDX WEB est une application web de calcul développée avec **Python**, **Flask** et la **programmation orientée objet (POO)**.

L'application permet d'effectuer des opérations mathématiques depuis une interface web, de consulter l'historique des calculs et d'effectuer des calculs via une **API REST JSON**.

## Fonctionnalités

- Effectuer une addition
- Effectuer une soustraction
- Effectuer une multiplication
- Effectuer une division
- Gérer les erreurs, notamment la division par zéro
- Consulter l'historique des calculs
- Utiliser une interface web avec Flask et Jinja2
- Effectuer des calculs via une API REST JSON

## Installation

### 1. Cloner le projet

```bash
git clone URL_DU_DEPOT_GITHUB
```

### 2. Accéder au projet

```bash
cd CALCULATEDX-WEB
```

### 3. Créer l'environnement virtuel

```bash
py -m venv .venv
```

### 4. Activer l'environnement virtuel sous Windows

```bash
.venv\Scripts\activate
```

### 5. Installer les dépendances

```bash
pip install -r requirements.txt
```
## Lancer l'application

Définissez la variable d'environnement `CALCULATEDX_SECRET_KEY` avant le
lancement. Utilisez une clé aléatoire générée une seule fois avec
`secrets.token_hex(32)` et conservez-la dans votre configuration d'environnement
pour les lancements suivants. Ne la versionnez pas. L'application refuse de
démarrer si cette variable est absente ou vide. Flask ne charge pas
automatiquement un fichier `.env` dans ce projet.

Après avoir activé l'environnement virtuel, lancer le serveur Flask :

```bash
py app.py
```

L'application est ensuite accessible dans le navigateur à l'adresse :

`http://127.0.0.1:5000`

## Sécurité Flask

Les cookies de session exigent HTTPS (`Secure`, `HttpOnly`, `SameSite=Lax`).
Le navigateur doit accéder à l'application en HTTPS pour conserver son historique
et son jeton CSRF. Le lancement HTTP décrit plus haut reste un serveur de
développement et ne constitue pas une configuration de production. HSTS n'est
pas activé tant que la topologie HTTPS n'a pas été validée.

`DEBUG` et `TESTING` sont désactivés par défaut. Les tests activent explicitement
`app.config["TESTING"] = True` dans leur configuration isolée, sans désactiver
le CSRF ou les en-têtes de sécurité. Les corps de requête sont limités à 16 Kio ;
un dépassement renvoie HTTP 413 (JSON pour `/api/`) avant toute écriture SQLite.
La CSP autorise uniquement les ressources locales et interdit les scripts inline
ainsi que l'intégration du site dans une iframe.

## API REST

Pour le serveur WSGI, le stockage persistant, les limites anti-abus et la recette
de production, consulter [le guide de déploiement](deploy/README.md).
Les modèles d'infrastructure nécessitent un choix d'hébergement et ne sont pas
des configurations déjà déployées.

CALCULATEDX WEB expose une API permettant d'effectuer des calculs à partir de données JSON.

### Endpoint

Toutes les requêtes de modification exigent un jeton CSRF associé à une session.
Pour utiliser l'API, chargez d'abord `GET /calcul`, récupérez la valeur du champ
caché `csrf_token`, puis envoyez-la dans l'en-tête `X-CSRF-Token` du POST en
conservant le cookie de session reçu. Un jeton absent ou invalide entraîne une
réponse JSON HTTP 400 sans enregistrement du calcul.

```text
POST /api/v1/calculer
```

### Exemple de requête

```json
{
    "nombre1": 10,
    "operation": "addition",
    "nombre2": 5
}
```

### Exemple de réponse

```json
{
    "resultat": 15
}
```

### Codes HTTP

- `200 OK` : le calcul a été effectué avec succès.
- `400 Bad Request` : la requête contient une erreur, un champ obligatoire est absent, l'opération est invalide ou une division par zéro est demandée.

## Contrat numérique

Les calculs utilisent des flottants Python binary64 et SQLite REAL, sans
arithmétique décimale exacte ni modification du schéma. Les opérandes et résultats
doivent être finis. Les entiers JSON et les saisies HTML en notation entière
(chiffres avec signe facultatif, sans point ni exposant) sont
acceptés uniquement si leur conversion en float est exacte : `2**53 + 1` est
refusé, mais `2**53 + 2`, `2**63` et `10**20` sont acceptés. Il n'existe pas de
plafond général à `2**53` pour les flottants.

Les saisies avec point ou exposant, les fractions et opérations suivent les arrondis binary64, y compris le sous-flux
vers zéro ; une exactitude décimale n'est pas garantie. Un nombre JSON déjà décodé
comme float est évalué selon cette valeur, sans reconstitution de son texte initial.
La cohérence signifie l'égalité numérique entre le résultat float de l'API et
celui relu depuis SQLite, pas l'identité textuelle ni la distinction entre +0 et -0.
Les erreurs numériques donnent HTTP 400 (JSON pour l'API, page d'erreur de calcul
pour le formulaire), sans enregistrement. Les erreurs SQLite restent HTTP 500.

## Structure du projet

```text
CALCULATEDX-WEB/
│
├── app.py
├── models.py
├── requirements.txt
├── README.md
│
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── calcul.html
│   └── historique.html
│
└── static/
    └── css/
        └── style.css
```

## Technologies utilisées

- **Python** : langage principal du projet
- **Flask** : framework web
- **HTML5** : structure des pages
- **CSS3** : mise en forme de l'interface
- **Jinja2** : génération dynamique des pages HTML
- **Git / GitHub** : gestion des versions et hébergement du code
- **Thunder Client** : test de l'API REST
