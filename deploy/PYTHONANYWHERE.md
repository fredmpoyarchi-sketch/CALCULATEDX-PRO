# PythonAnywhere Free — préparation du lot 2

Pour le lot 3, suivre [la stratégie des données](DATA_RELIABILITY.md) : choix de
stockage, préparation versionnée avant workers, sauvegarde et restauration.

Aucun compte créé, site rechargé ou fichier envoyé par cette préparation. Les
étapes ci-dessous sont manuelles et ne doivent être exécutées qu'après décision
de déployer. Les exemples `YOUR_USERNAME` sont à remplacer hors du dépôt.

## Capacités confirmées et limites

Documentation consultée le 21 octobre 2026 : offre Free avec un site et un worker,
512 Mio de stockage, deux consoles et une échéance de site d'un mois à renouveler.
Les nouveaux comptes gratuits n'ont ni tâches planifiées ni always-on. L'accès
Internet sortant est restreint. Les anciennes offres peuvent différer : vérifier
le tableau de bord du compte et les conditions en vigueur.

La capacité CPU annoncée pour consoles/tâches n'est pas un quota de requêtes web.
Aucune garantie de limitation applicative par IP n'est supposée. Pas de serveur
Nginx, service systemd, daemon de supervision ou Waitress à lancer dans le compte.
Les modèles autonomes du précédent lot restent des alternatives hors PythonAnywhere.

**Risque SQLite explicite :** PythonAnywhere décrit un système de fichiers réseau
et déconseille SQLite pour les applications web de production, notamment avec
plusieurs workers. Un worker réduit la concurrence, sans annuler ce risque ni
garantir les performances. Garder le journal SQLite existant : ne pas activer WAL.
Évaluer latence/verrouillages sur une base dédiée ; si inacceptables, changer
d'hébergement ou de stockage dans un lot distinct avant publication. Aucune
migration ni nouvelle base n'est créée par ce profil.

Sources officielles : [Free](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/),
[prix et quotas](https://www.pythonanywhere.com/pricing/),
[SQLite et filesystem](https://help.pythonanywhere.com/pages/MySiteIsSlow/).

## Architecture et version Python

```text
Navigateur HTTPS -> frontal PythonAnywhere -> worker WSGI géré (unique)
                                             -> Flask + limiteur mémoire
                                             -> SQLite privée persistante
```

Utiliser la configuration WSGI classique, pas le système ASGI expérimental. Le
module `pythonanywhere_wsgi.py` exporte `application`, sans `app.run`, bind réseau
ni démarrage Waitress. Le venv existant en local n'est pas à transférer.

La table officielle des images consultée annonce Python 3.13 sur l'image `innit` ;
elle ne confirme pas Python 3.14. Vérifier les versions disponibles dans **Account
> System image** et **Web**. Utiliser la même version pour le venv et le site,
initialement 3.13 si disponible, et exécuter tous les tests sur place avant de
publier. La CI prépare une matrice 3.13/3.14 ; une configuration de CI n'est pas
une exécution réussie sur ces deux versions.

Depuis une console Bash, après transfert autorisé du code dans
`/home/YOUR_USERNAME/CALCULATEDX-PRO` :

```bash
mkvirtualenv calculatedx --python=/usr/bin/python3.13
cd /home/YOUR_USERNAME/CALCULATEDX-PRO
python -m pip install -r requirements.txt
python -m pip check
python -B -m unittest discover -s tests -v
```

Adapter la version au compte. Pour une nouvelle console : `workon calculatedx`.
Ne pas utiliser `pip --user` dans le virtualenv. La dépendance Waitress conservée
sert au profil autonome et à ses tests, elle ne lance rien lors du chargement WSGI.

Sources : [versions](https://help.pythonanywhere.com/pages/PythonVersions/),
[Flask/venv/WSGI](https://help.pythonanywhere.com/pages/Flask/).

## Configuration privée et SQLite

Prévoir un fichier existant déjà préparé, par exemple
`/home/YOUR_USERNAME/.local/share/calculatedx/history.sqlite3`, hors dépôt et hors
de tout mapping statique. Le répertoire et le fichier doivent rester privés
(0700/0600), avec droits d'écriture pour le worker, y compris les fichiers journal.
La préparation et le transfert d'une éventuelle copie sont une opération séparée
à autoriser, avec sauvegarde et contrôle ; jamais de remplacement/purge d'une base
existante. Ne pas importer directement `app` avant la configuration du stockage.

La configuration est chargée depuis
`~/.config/calculatedx/production.json`, hors Git, et définit exactement :

| Variable | Valeur à provisionner |
| --- | --- |
| `CALCULATEDX_SECRET_KEY` | Clé aléatoire créée une seule fois, stable aux reloads. |
| `CALCULATEDX_DB_PATH` | Chemin absolu de la base privée existante. |
| `CALCULATEDX_HOSTNAMES` | Domaine exact affiché dans Web, par exemple `YOUR_USERNAME.pythonanywhere.com` ou sa variante EU. |

Le chargeur refuse les permissions groupe/autres sous Linux et une configuration
dans le dépôt. Il injecte ces trois valeurs dans `os.environ` **avant** l'import
Flask. Un `export` dans une console ne suffit pas à configurer les workers web.
Le port du profil autonome n'est pas utilisé sur PythonAnywhere.

Pour créer uniquement le fichier privé lors de la préparation manuelle future,
adapter les deux valeurs non secrètes ci-dessous dans une console Python. Cette
procédure génère la clé sans l'afficher et refuse d'écraser un fichier existant :

```python
import json, os, secrets
from pathlib import Path

folder = Path.home() / ".config" / "calculatedx"
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(folder, 0o700)
values = {
    "CALCULATEDX_SECRET_KEY": secrets.token_hex(32),
    "CALCULATEDX_DB_PATH": "/home/YOUR_USERNAME/.local/share/calculatedx/history.sqlite3",
    "CALCULATEDX_HOSTNAMES": "YOUR_USERNAME.pythonanywhere.com",
}
fd = os.open(folder / "production.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(values, stream)
```

Ne jamais afficher/copier ce JSON dans une issue, un log ou un commit. Ne pas
recréer la clé après chaque modification. Le chemin SQLite local de `database.py`
reste compatible avec le développement ; ce profil remplace `database.DB_PATH`
avant l'import de l'application. La validation préliminaire ouvre la base en
lecture seule ; la version de schéma doit être préparée avant les workers, qui
n'effectuent plus de migration pendant leur démarrage.

## Configuration de l'onglet Web

Dans une future configuration manuelle, sélectionner **Manual configuration**, la
version Python choisie et le virtualenv `/home/YOUR_USERNAME/.virtualenvs/calculatedx`.
Ouvrir le lien du fichier WSGI fourni par PythonAnywhere, et utiliser :

```python
import sys
project = "/home/YOUR_USERNAME/CALCULATEDX-PRO"
if project not in sys.path:
    sys.path.insert(0, project)
from pythonanywhere_wsgi import application
```

Ne pas exécuter `production.py`, `flask run` ou `app.run`. Le profil force
`DEBUG=False`, `TESTING=False` et conserve Secure/HttpOnly/SameSite=Lax, CSP et CSRF.
Après toute modification du code, du venv ou du fichier privé : bouton **Reload**
du site. Le même fichier de configuration et la même base doivent rester en place.

Templates et ressources sont résolus par Flask relativement à `app.py`, pas au
répertoire courant du worker. Aucun mapping Web n'est nécessaire initialement :
Flask sert `/static/css/style.css` et `/static/js/historique.js` avec les en-têtes
du lot 1 et les limites du profil. Ne jamais mapper `/`, le dépôt complet, les
templates ou un répertoire privé dans la section Static files.

Un mapping optionnel `/static/` vers
`/home/YOUR_USERNAME/CALCULATEDX-PRO/static/` réduit la charge du worker mais
contourne les hooks Flask et leurs en-têtes/quotas sur ces seuls fichiers. Ne
l'activer qu'après vérification des types MIME et protections réellement fournis.
Voir [mappings statiques](https://help.pythonanywhere.com/pages/StaticFiles/).

## HTTPS et proxies

Le domaine PythonAnywhere fourni possède un certificat HTTPS géré par la
plateforme. Valider l'accès HTTPS puis activer **Force HTTPS** dans Web et Reload ;
vérifier réellement la redirection HTTP. Envoyer directement les POST en HTTPS,
sans compter sur une redirection après émission d'un corps en HTTP. Aucun HSTS
n'est ajouté. Aucun `ProxyFix` n'est activé : les routes actuelles utilisent des
URL relatives et les cookies Secure sont explicites.

Le limiteur de ce profil utilise uniquement `X-Real-IP`, que la documentation
PythonAnywhere décrit comme défini par son load balancer. Ne pas utiliser ce profil
derrière un serveur qui accepte cette valeur du client. `REMOTE_ADDR` correspond
normalement au load balancer et XFF peut contenir des valeurs falsifiées : ils ne
servent pas aux quotas. Pas de confiance automatique dans le premier élément XFF.
La recette doit confirmer l'écrasement de X-Real-IP envoyé par un client ; si cette
garantie ne s'applique pas au compte/topologie, bloquer la publication ou revoir
la sélection d'origine. Ne pas ajouter de CDN non validé devant ce domaine Free.

Sources : [certificat](https://help.pythonanywhere.com/pages/HTTPSSetup/),
[Force HTTPS](https://help.pythonanywhere.com/pages/ForcingHTTPS/),
[IP client](https://help.pythonanywhere.com/pages/WebAppClientIPAddresses/).

## Anti-abus et HTTP 429

Le profil installe un token bucket global (20 requêtes/s, burst 40) et un quota par
origine (1 requête/s, burst 10), sur toutes les requêtes traitées par Flask, avant
le CSRF et SQLite mais après la limite de corps. Un refus donne JSON HTTP 429,
Retry-After en secondes et Cache-Control: no-store, avec les en-têtes du lot 1.
La clé ne dépend pas du cookie. IPv4 canonique, IPv4 mappée normalisée, et IPv6
regroupée par /64 ; une IP absente/invalide partage le quota « unknown ».

État limité à 4096 origines en mémoire ; à saturation, les nouvelles origines
partagent un quota de débordement sans évincer les quotas actifs. Les quotas
expirés peuvent être libérés. Aucun fichier de compteur ni modification SQLite,
Redis, dépendance ou tâche planifiée supplémentaire. Seuils à ajuster dans le
profil après mesure, en tenant compte des visiteurs derrière un NAT.

Limites : un reload remet ces quotas à zéro, un second worker aurait un état
distinct, et les requêtes rejetées arrivent quand même au worker. Ce mécanisme
réduit les calculs/écritures abusifs mais ne protège pas contre DDoS, files d'attente
du frontal ou épuisement réseau. Ne pas promettre de plafond distribué ou durable.
La limite de corps Flask reste 16 Kio ; délais, limites de file et erreurs du
frontal géré sont à vérifier, sans supposer l'accès à une configuration Nginx.

## Journaux, espace et recette après déploiement

Les liens **Error log**, **Server log** et **Access log** se trouvent dans Web.
Ouvrir Error log après un échec d'import ou de reload ; ne pas publier son contenu
brut. Le middleware applicatif envoie à stderr méthode normalisée, statut et durée,
sans corps, cookie, CSRF, IP ou URL. Les logs gérés par la plateforme sont distincts
et peuvent contenir URI/IP : vérifier accès, rétention et quota. Ne jamais placer
de secret dans une URL, y compris dans les tests.

Sur Free, ne pas présumer de tâche planifiée/minuteur always-on. Contrôler le quota
du compte manuellement et poser un rappel externe pour renouvellement, sauvegardes
et inspection des 5xx. `monitor.py` du profil autonome mesure le disque du système,
pas le quota privé du compte : il ne garantit pas d'alerte avant les 512 Mio.

Sur une base de recette dédiée, après autorisation de déployer :

1. Venv/version concordants, suite complète verte et import WSGI depuis un autre
   répertoire courant ; démarrage refusé sans clé ou base préparée.
2. Certificat valide, HTTP redirigé, cookie Secure/HttpOnly/SameSite=Lax, CSP et
   en-têtes du lot 1 sur pages, erreurs et fichiers statiques.
3. Deux navigateurs indépendants : calculs HTML/API, historique complet/paginé,
   filtres, statistiques et suppression croisée refusée ; CSRF absent/invalide : 400.
4. Corps valide de 16 Kio accepté, +1 octet refusé avec 413 sans nouvelle ligne ;
   contrôler aussi le transfert chunked et les éventuels rejets du frontal.
5. Une rafale autorisée de GET `/` doit produire au moins un 429 avec Retry-After,
   puis revenir à 200 après repos. Exemple borné, uniquement sur la recette :
   `seq 1 15 | xargs -P 5 -I{} curl -s -o /dev/null -w '%{http_code}\n' https://YOUR_USERNAME.pythonanywhere.com/`.
   Vérifier séparément le quota global avec plusieurs origines contrôlées ; les
   tests unitaires utilisent une horloge simulée et aucun réseau.
6. Changer/effacer le cookie et falsifier XFF ne réinitialise pas le quota d'origine ;
   envoyer un faux X-Real-IP et confirmer que le frontal l'écrase réellement.
7. Reload avec même clé : cookie et historique encore reconnus ; état des quotas
   réinitialisé comme documenté. Vérifier également la persistance du fichier.
8. Tester la restauration sur copie, sans écriture concurrente par une console ;
   mesurer latence SQLite et erreurs de verrouillage. Aucun WAL, purge ou montée
   à plusieurs workers sans nouvelle revue.
9. Vérifier erreurs SQLite HTTP 500, visibilité des 5xx, absence de marqueurs
   secrets dans les journaux accessibles, quota de stockage et date de renouvellement.

Ne pas annoncer une mise en production validée avant ces contrôles sur le compte
réel, en particulier les risques du filesystem réseau pour SQLite.
