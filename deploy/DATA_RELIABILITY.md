# Fiabilité des données — lot 3

## Architecture recommandée et choix bloquant

Le minimum recommandé pour conserver des historiques publics est une instance
applicative avec SQLite sur disque persistant **local**, privé, et des snapshots
vérifiés exportés hors hôte. Aucun nouveau moteur ni adaptateur n'est nécessaire.
SQLite n'ajoute pas de coût de licence ; l'hébergement, le stockage et les exports
restent à budgéter, sans présumer d'une offre gratuite fiable.

PythonAnywhere décrit un filesystem réseau et déconseille SQLite pour les sites
de production. Un worker réduit les conflits sans prouver la fiabilité des verrous
ou de fsync. Un test de charge réussi ne démontre pas la durabilité face aux pannes.
WAL n'est pas une solution sur filesystem réseau et n'est pas activé.

Comparaison, documentation consultée le 21 octobre 2026 :

| Option | Compatibilité avec PythonAnywhere Free | Coût, complexité et décision |
| --- | --- | --- |
| SQLite, trafic faible | Stockage privé possible, mais filesystem déconseillé pour SQLite en production. | Aucun moteur supplémentaire ; prototype/recette avec risque explicite, pas une fiabilité garantie. |
| MySQL PythonAnywhere | Disponible sur certains comptes anciens, pas les nouveaux Free. Compte/date/région à vérifier. | Adaptateur et migration à autoriser séparément ; disponibilité gratuite non présumée. |
| PostgreSQL hébergé | Aucune disponibilité Free confirmée dans les offres consultées. | Offre et moteur à choisir ; aucune intégration ici. |
| Base SQL externe native | Les sorties Free sont HTTP(S) vers une allowlist, pas un accès TCP général aux bases. | Connexion, fournisseur, prix et SLA non vérifiés ; ne pas compter sur cette option. |
| Service de données par API HTTPS | Conditionnel à l'endpoint autorisé et aux conditions fournisseur. | Secrets, latence et nouvelle couche d'accès aux données ; gratuité et compatibilité non vérifiées. |
| SQLite sur disque local ailleurs | Hors de la cible Free actuelle. | Peu de changements logiciels, hébergement et copies externes à budgéter ; recommandation minimale pour garder le moteur. |

Sources : [PythonAnywhere et SQLite](https://help.pythonanywhere.com/pages/MySiteIsSlow/),
[Free et comptes anciens](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/),
[offres](https://www.pythonanywhere.com/pricing/),
[réseau Free](https://help.pythonanywhere.com/pages/403ForbiddenError/),
[SQLite sur réseau](https://www.sqlite.org/useovernet.html),
[WAL](https://www.sqlite.org/wal.html).

**Blocage à lever avant publication :** choisir un stockage/hébergement approprié,
ou accepter explicitement de rester en prototype Free. Un changement de moteur
requiert une autorisation distincte. Aucun moteur, compte, service externe ni
déploiement n'est créé ici. Les garanties du compte et de son filesystem restent
non vérifiées ; les outils ne les réparent pas.

## Chemins privés et préparation unique

`CALCULATEDX_DB_PATH` reste un chemin absolu hors dépôt et mappings HTTP, par exemple
`/home/YOUR_USERNAME/.local/share/calculatedx/history-v1.sqlite3`. Répertoires Linux
0700, fichiers 0600 ; sous Windows, ACL privées à vérifier. Le worker a besoin
d'écrire aussi le journal SQLite dans ce répertoire. Le secret Flask reste dans la
configuration privée du lot 2, jamais dans la base ni son manifeste.

`PRAGMA user_version = 1` versionne désormais le schéma. La migration additive
conserve les identifiants, séquences, dates, valeurs et calculs NULL ; elle ajoute
si nécessaire `visitor_id` nullable et son index. Elle est transactionnelle et
idempotente, et refuse une version future inconnue. La version 0 des anciennes
bases nécessite une préparation avant activation, même si la colonne existe déjà.

Le profil WSGI valide version, colonnes et index puis désactive l'initialisation
de la calculatrice : **aucun CREATE/ALTER/migration au démarrage des workers**.
Une base non préparée est refusée. Le mode local `Calculatrice()` reste compatible.

Les commandes suivantes sont une procédure future à autoriser, pas des opérations
exécutées sur vos données. Les répertoires privés doivent déjà exister. Arrêter
réellement le site et les consoles écrivantes : `--workers-stopped` est une
attestation opérateur, pas un mécanisme d'arrêt. Un simple Reload ne prouve pas
l'arrêt des anciens workers. Sauvegarder/exporter l'état courant avant maintenance.

Préparer une nouvelle base vide :

```text
python -B data_admin.py prepare --destination /PRIVATE/history-v1.sqlite3 --workers-stopped
```

Ou migrer une copie d'une base privée autorisée, en conservant sa source :

```text
python -B data_admin.py prepare --source /PRIVATE/legacy-history.sqlite3 --destination /PRIVATE/history-v1.sqlite3 --workers-stopped
```

Vérifier la copie et son manifeste, la tester puis pointer la configuration privée
sur ce nouveau chemin avant de démarrer un worker. Conserver source et ancienne
configuration. Relancer sur la même destination est refusé, sans écrasement ; la
migration elle-même reste idempotente. Aucun outil ne choisit une base implicite :
tout chemin relatif, dans le dépôt ou nommé `calculatedx.db` est refusé avant son
ouverture. Aucune commande de ce guide n'utilise la base locale protégée.

## Sauvegarde cohérente et manifeste

```text
python -B data_admin.py backup --source /PRIVATE/history-v1.sqlite3 --destination /PRIVATE_BACKUPS/snapshot-UTC-unique.sqlite3
python -B data_admin.py verify --snapshot /PRIVATE_BACKUPS/snapshot-UTC-unique.sqlite3 --manifest /PRIVATE_BACKUPS/snapshot-UTC-unique.sqlite3.manifest.json
```

L'API `sqlite3.Connection.backup` copie un snapshot transactionnel depuis une
connexion en lecture seule ; les écritures non commitées ne sont pas incluses.
Pas de copie brute d'un fichier ouvert. La cohérence dépend encore des garanties
du filesystem. Préférer une fenêtre calme/écritures suspendues sur PythonAnywhere.

L'outil contrôle `integrity_check` et `foreign_key_check`, puis calcule SHA-256,
taille, version et nombres de lignes totales/NULL ; un manifeste privé daté UTC
accompagne le snapshot. Les bases préparées/restaurées ont aussi un manifeste
initial, qui devient obsolète dès qu'elles servent des écritures. Pour une base
active, créer un nouveau snapshot avant vérification.

Les temporaires sont privés sur le volume de sortie. Les fichiers sont synchronisés
avant publication ; des liens durs publient sans remplacer une destination même en
cas de collision concurrente. Sous POSIX, le répertoire est aussi synchronisé.
Vérifier le support de ces opérations sur l'hébergement : sinon l'outil échoue,
sans fallback d'écrasement. Les tests temporaires ne prouvent pas la résistance
aux pannes du stockage réel.

Base et manifeste ne forment pas une transaction unique de filesystem : une
interruption peut laisser un fichier isolé. **Seule une paire passant verify est
utilisable.** Une archive publiée n'est pas effacée pour retenter ; utiliser un
nouveau nom et examiner l'échec. Seuls les temporaires créés par l'outil sont
nettoyés ; aucun historique source n'est supprimé. Les destinations existantes,
y compris les manifestes, sont refusées.

Un contrôle de progression borne la copie à 30 s par défaut dans l'API Python,
mais ne peut interrompre un appel système bloqué. Le budget d'exécution externe
reste à définir. Exit 1 signale un échec avec diagnostic générique sans données
ni chemin ; exit 0 indique une validation locale, pas une garantie absolue.

SHA-256 détecte une altération accidentelle, pas une falsification d'une paire
base/manifeste. Protéger les deux fichiers et exporter une copie chiffrée hors hôte
avec une clé distincte. Aucun chiffrement maison, upload ou dépendance n'est ajouté.
Références : [API SQLite](https://www.sqlite.org/backup.html),
[API Python](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).

## Restauration et bascule

```text
python -B data_admin.py restore --snapshot /PRIVATE_BACKUPS/snapshot-UTC-unique.sqlite3 --manifest /PRIVATE_BACKUPS/snapshot-UTC-unique.sqlite3.manifest.json --destination /PRIVATE_RECOVERY/restored-unique.sqlite3
```

L'empreinte est vérifiée avant ouverture SQLite, puis intégrité, métadonnées et
schéma. La restauration crée un nouveau fichier et manifeste ; elle ne remplace
jamais la base active. Une archive ancienne peut être vérifiée, mais nécessite
`prepare --source ...` vers une copie migrée avant activation si sa version est 0.

La restauration copie les octets du snapshot vers un temporaire privé, puis
compare son empreinte, sa taille et ses métadonnées à celles vérifiées avant
publication. Une modification de l'archive entre vérification et copie est
refusée. Ce chemin concerne une archive figée ; la sauvegarde d'une base active
continue d'utiliser l'API SQLite, jamais une copie brute.

Recette privée obligatoire avant bascule :

1. Vérifier la paire, restaurer à un chemin neuf et contrôler lignes, NULL, dates,
   identifiants, séquences, version et valeurs binary64.
2. Avec deux sessions isolées : historique/pagination/filtres/statistiques propres,
   calculs HTML/API, CSRF actif et suppression croisée refusée. Conserver HTTP 500
   en cas d'erreur SQLite et vérifier l'absence de DDL pendant l'import WSGI.
3. Mesurer le temps de récupération et noter l'instant du snapshot choisi.
4. Pour une bascule autorisée, arrêter tous les écrivains, sauvegarder l'état
   courant, changer le chemin privé puis démarrer un worker. Ne jamais remplacer
   un fichier sous des connexions ouvertes ; conserver les originaux.
5. Vérifier après reprise et réaliser une nouvelle copie externe.

Revenir à un snapshot perd les calculs postérieurs et peut réintroduire des calculs
supprimés après sa création par leur propriétaire. Autoriser explicitement ce
retour dans le temps ; aucune fusion automatique ni purge n'est implémentée.

## Historiques anonymes, conservation et objectifs

Le snapshot conserve `visitor_id`, pas les cookies des navigateurs. Sauvegarder le
secret Flask séparément, avec accès restreint. La même clé et un cookie encore
valide permettent de retrouver le propriétaire après reprise ; perte/expiration
du cookie ou rotation de clé peuvent empêcher cet accès. Restaurer une base seule
ne garantit donc pas la récupération utilisateur.

Sans compte ni autre preuve, ne pas réattribuer un historique sur simple demande.
Les données NULL restent conservées et invisibles. Une suppression par le
propriétaire ne garantit pas un effacement immédiat des snapshots antérieurs.

Objectifs proposés, à approuver et démontrer : RPO ≤ 24 h et RTO ≤ 4 h. Ils supposent
des snapshots quotidiens exportés et un exercice chronométré ; ils ne sont pas
assurés par le code. Les nouveaux Free n'ont pas de tâche planifiée, et aucun
opérateur/service d'automatisation n'est configuré. Si ces objectifs ne peuvent
être tenus, revoir explicitement l'objectif ou l'hébergement.

Prévoir une copie avant maintenance, la dernière validée et une précédente hors
hôte. Décider de la durée de conservation, du responsable, de la fréquence des
exercices et de la gestion des suppressions dans les archives avant publication.
**Aucune purge, rotation destructive ou expiration automatique n'est activée.**
Le quota Free est partagé entre venv, code, données, logs, temporaires et archives.

Points non vérifiés/bloquants : compte/région/date et base hébergée réellement
disponible ; verrous/fsync/liens durs et quota du stockage cible ; endpoint,
allowlist, prix/SLA d'un service externe ; opérateur et budget pour sauvegardes
externes/alertes ; version Python/SQLite et recette réelle de récupération.
Sans stockage approprié et récupération démontrée, le service n'est pas annoncé
prêt à conserver des historiques publics de manière fiable.
