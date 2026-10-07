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

Après avoir activé l'environnement virtuel, lancer le serveur Flask :

```bash
py app.py
```

L'application est ensuite accessible dans le navigateur à l'adresse :

`http://127.0.0.1:5000`

## API REST

CALCULATEDX WEB expose une API permettant d'effectuer des calculs à partir de données JSON.

### Endpoint

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