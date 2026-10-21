# Production — lot 2

**Cible désormais retenue : PythonAnywhere Free.** Suivre
[le guide dédié](PYTHONANYWHERE.md). Ce document conserve le profil autonome
alternatif : ne pas lancer Waitress, Nginx ou systemd sur PythonAnywhere Free.

## Statut et décisions bloquantes

Aucun hébergement, OS serveur, domaine ni fournisseur TLS n'est confirmé. Aucun
service n'a été installé ou exposé. Les fichiers `*.example` sont des modèles à
adapter, pas une configuration opérationnelle validée. Ils contiennent des chemins
`/REPLACE` et le domaine réservé `calculator.example.invalid`.

Décisions nécessaires avant publication :

- OS et hébergeur, accès réseau et éventuel CDN/load balancer ;
- domaine, certificats, renouvellement et responsable de l'exploitation ;
- volume local persistant, droits, sauvegardes/restauration et capacité disque ;
- gestionnaire du processus et des secrets, collecte/rotation des logs et alertes ;
- budgets de débit/concurrence, seuils d'alerte et recette de charge acceptables.

## Architecture minimale proposée

```text
Navigateur --HTTPS--> frontal TLS + limites globales/IP
                        |
                        +--loopback HTTP--> Waitress (1 processus, 4 threads)
                                             |
                                             +--> SQLite sur disque local persistant privé
```

Waitress 3.0.2 est épinglé dans `requirements.txt` ; il fonctionne sur Windows et
Linux et ne termine pas TLS. Un seul processus applicatif, sans réplication ni
autoscaling, accède à une seule base. Les threads ne partagent pas les connexions
SQLite : l'application ouvre et ferme une connexion pour chaque opération.

Le frontal doit être sur le même hôte pour le profil fourni. Si l'hébergeur impose
un frontal distant, un conteneur séparé ou un CDN, la topologie doit être revue
avant utilisation. Ne pas remplacer le bind loopback par `0.0.0.0` pour contourner
cette restriction. Ne pas exposer le répertoire du dépôt comme racine web.

## Variables et lancement WSGI

| Variable | Contrat |
| --- | --- |
| `CALCULATEDX_SECRET_KEY` | Secret aléatoire persistant, obligatoire (minimum 32 caractères contrôlé). Générer 32 octets aléatoires, par exemple avec `secrets.token_hex(32)` ; la longueur seule ne garantit pas l'entropie. Injecté hors dépôt par le gestionnaire de secrets/service. Identique après redémarrage. |
| `CALCULATEDX_DB_PATH` | Chemin absolu d'un fichier SQLite existant et déjà préparé, hors dépôt, sur stockage persistant local. |
| `CALCULATEDX_HOSTNAMES` | Noms DNS exacts séparés par virgules, sans schéma, port ni joker. Host non autorisé : HTTP 400. |
| `CALCULATEDX_PORT` | Port loopback, 8080 par défaut, entier de 1 à 65535. Adapter le frontal si différent. |

Le programme ne lit aucun `.env`. Ne pas mettre de secret dans une commande
versionnée, un argument de processus ou un log. Provisionner la clé via le canal
privé de l'hébergeur ; ne pas la régénérer au redémarrage. La rotation invalide les
sessions existantes si aucune transition n'est organisée.

Après activation du venv et injection des variables par le service :

```text
python -m pip install -r requirements.txt
python -B production.py
```

Cette commande doit être exécutée par le superviseur, jamais par le serveur de
développement Flask. `app.run`, `flask run` et `--debug` sont exclus du lancement
public. Le processus vérifie l'environnement et le schéma en lecture seule avant
d'importer l'application. Il refuse une base manquante, ancienne, située dans le
dépôt ou dépourvue de l'index visiteur. Il n'effectue aucune nouvelle migration.
Le lot 3 exige désormais une préparation versionnée avant les workers : aucun DDL
à leur démarrage. Consulter [la procédure des données](DATA_RELIABILITY.md) pour
préparer une copie et tester sauvegarde/restauration, sans écraser les originaux.

Le compte de service doit pouvoir écrire dans le répertoire de la base et ses
fichiers SQLite auxiliaires, mais pas dans le code. Restreindre les ACL au compte
de service et aux administrateurs ; ne pas partager ce volume avec d'autres
locataires et ne pas le placer sur un partage réseau. La persistance n'est pas une
sauvegarde : restauration à tester séparément avant publication.

## HTTPS, cookies et confiance dans les proxies

Les cookies `Secure`, `HttpOnly`, `SameSite=Lax` et la CSP du lot 1 restent actifs.
Le frontal doit terminer HTTPS avec certificat valide et renouvellement testé.
HTTP doit uniquement rediriger vers un domaine HTTPS canonique fixé par
l'opérateur, sans transmettre de requête applicative. Le modèle utilise HTTP 308 ;
un client doit envoyer directement ses POST en HTTPS pour éviter d'émettre le corps
en clair lors de la première requête HTTP. Aucun HSTS n'est ajouté.

Le profil portable n'active **ni ProxyFix ni trusted_proxy**. Waitress supprime les
en-têtes proxy non fiables et le modèle Nginx ne les transmet pas. Le `Host` est
fixé par Nginx et validé par Flask. `REMOTE_ADDR` côté application est donc celui du
frontal local, et `request.scheme` reste HTTP. Les URL actuelles et les redirections
sont relatives ; les cookies Secure n'en dépendent pas. Ne pas ajouter de limite IP
côté Flask à partir de cette adresse, ni de génération d'URL absolue sans revue.

Une future confiance dans `Forwarded`/`X-Forwarded-*` exige de connaître exactement
les proxies, leurs adresses, le nombre de sauts, la réécriture des en-têtes et le
blocage de tout accès direct. Ne jamais faire confiance à `*`, aux IP déclarées par
un client ou activer simultanément deux mécanismes de réécriture par défaut.

## Anti-abus : implémenté et préparé

Dans `production.py`, réellement implémenté et testé : bind `127.0.0.1`, 4 threads,
100 connexions, timeout d'inactivité 30 s, nettoyage 5 s, en-têtes plafonnés à 8 Kio,
corps Waitress plafonné à 32 Kio et tracebacks non exposées. Flask conserve son
plafond de 16 Kio avant CSRF/SQLite. La marge WSGI permet à Flask de rendre ses 413
JSON ; au-delà du plafond serveur, le 413 peut être une réponse texte de Waitress.

Dans `nginx.conf.example`, **préparé mais non activé ni validé sur un serveur** :

- 5 requêtes/s par IP réseau, burst 10 ;
- 50 requêtes/s globales pour le site, burst 50 ;
- refus HTTP 429 JSON avec Retry-After, indépendant du cookie et du CSRF ;
- corps limité à 16 Kio, en-têtes/corps inactifs au-delà de 10 s, connexions
  persistantes 15 s et délais proxy 2/15/15 s ;
- aucune mise en cache des réponses personnalisées ; aucune exposition directe
  de SQLite ou du dépôt.

Le modèle suppose **un Nginx Linux directement connecté à Internet, sans CDN/LB**.
La clé par origine est son IP TCP `$binary_remote_addr`, jamais un XFF arbitraire.
Les zones sont partagées entre workers Nginx. Les IP derrière un NAT partagent la
limite ; IPv6 et attaques distribuées nécessitent aussi le plafond global. Les
valeurs sont un point de départ à mesurer, pas une capacité promise de SQLite.
Changer de cookie ne contourne pas ces limites. Les rejets du frontal peuvent être
HTML (413/408/504), contrairement aux erreurs JSON émises par Flask.

Ces délais limitent l'inactivité entre opérations réseau, pas la durée totale d'un
client lent ou le temps CPU d'un thread. Un timeout proxy n'annule pas un calcul
déjà soumis à Flask. La plateforme doit définir les budgets globaux de connexions,
mémoire, durée totale et protection DDoS. Le profil WSGI seul ne fournit pas de 429 :
la validation du frontal anti-abus est une condition bloquante de publication.

## Supervision et logs

Le middleware d'accès journalise seulement méthode normalisée, code HTTP et durée.
Pas d'URL, paramètres, IP, corps, cookie, CSRF ou en-têtes. Une réponse 5xx utilise
le niveau ERROR. Les exceptions applicatives existantes restent journalisées
côté serveur avec leurs piles ; protéger l'accès à ces journaux et ne jamais y
ajouter l'environnement ou les requêtes complètes.

Le modèle Nginx exclut aussi URI, IP et en-têtes de son access log. Ses journaux
d'erreur natifs, qui peuvent inclure les requêtes, sont désactivés dans le vhost
HTTPS modèle. Les erreurs 5xx sont suivies par l'access log ; vérifier également les
logs globaux de l'installation. Un collecteur avec filtrage validé peut remplacer
cette désactivation après choix de l'hébergeur. Activer une rotation avec rétention
bornée ; aucun collecteur, timer ou abonnement d'alerte n'est installé par ce lot.

`python -B monitor.py` consulte uniquement l'espace du volume de
`CALCULATEDX_DB_PATH`, sans ouvrir SQLite et sans utiliser le secret Flask.
Il émet un JSON sans chemin : exit 0 pour OK, exit 2 pour état critique/inconnu.
Le seuil proposé est au moins 1 Gio **et** 10 % libres. Le valider selon le volume
cible ; le code accepte d'autres seuils lors de son intégration. Programmer une
exécution chaque minute et router exit 2 vers une alerte opérateur.

Préparer aussi : sonde HTTP locale sur `/` avec le Host autorisé, timeout 5 s,
sonde HTTPS extérieure et alerte après trois échecs ; alerte sur 5xx > 1 % pendant
5 min et sur les boucles de redémarrage. La sonde HTTP ne prouve pas l'état SQLite :
les calculs et statistiques sont vérifiés lors de la recette. Les seuils doivent
être ajustés au volume réel de trafic et au contrat de disponibilité.

`calculatedx.service.example` prépare, pour Linux/systemd seulement, un compte
dédié, Restart=on-failure, un anti-boucle de redémarrage et un système de fichiers
en lecture seule hors répertoire persistant. Adapter les chemins, permissions,
budgets mémoire/CPU et stockage temporaire avant `systemd-analyze verify`. Sous
Windows, configurer un service équivalent avec récupération après échec et collecte
des sorties ; aucun gestionnaire Windows n'est supposé installé.

## Recette avant publication

Sur une copie dédiée, jamais sur la base locale de développement :

1. Valider les décisions bloquantes et sauvegarder/restaurer la base de recette.
   Vérifier ACL, volume persistant et absence d'accès HTTP au répertoire de données.
2. Installer les dépendances dans un venv Python 3.14 et exécuter toute la suite.
   Le lancement sans secret, sans base préparée ou avec un chemin relatif doit
   échouer sans créer de fichier ni exposer de valeur sensible.
3. Démarrer le service avec les variables privées. Vérifier le bind loopback,
   l'absence d'écoute publique du port 8080 et le rejet des Host non autorisés.
4. Adapter puis valider le frontal (`nginx -t` dans la topologie modèle), le
   certificat, son renouvellement, la redirection HTTP et les pare-feu IPv4/IPv6.
   Tester les en-têtes Lot 1 sur les succès et erreurs. HSTS doit rester absent.
5. Dans deux navigateurs HTTPS indépendants : calculs HTML/API, CSRF invalide,
   historique, filtres, statistiques et suppression croisée refusée. Vérifier les
   trois attributs du cookie et la confirmation JavaScript sous CSP.
6. Vérifier 16 Kio acceptés, 16 Kio + 1 refusé avant SQLite, y compris transfert
   chunked. Le frontal ne doit pas avaler les erreurs SQLite HTTP 500.
7. Depuis un générateur autorisé : déclencher la limite IP puis, avec plusieurs
   origines contrôlées, la limite globale. Attendre HTTP 429 et Retry-After ;
   changer de cookie et falsifier XFF ne doivent pas réinitialiser le quota.
8. Tester corps lent, connexion inactive et lecture lente ; mesurer les délais
   et ressources. Conserver les budgets mesurés et les limites NAT acceptables.
9. Redémarrer le service puis redéployer : même secret, même fichier, mêmes
   historiques. Arrêter brutalement le processus sur la recette et vérifier sa
   récupération, sans nouveau fichier de base ni purge des lignes NULL.
10. Simuler 5xx et alerte disque via des seuils de sonde sur la recette, sans remplir
    le volume de production. Vérifier réception des alertes, rotation et absence de
    marqueurs secrets/cookies/CSRF dans tous les journaux collectés.

Aucun feu vert public avant cette recette sur l'infrastructure effectivement choisie.

Références : [Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html),
[proxies Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html),
[limites Nginx](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html),
[déploiement Flask](https://flask.palletsprojects.com/en/stable/deploying/).
