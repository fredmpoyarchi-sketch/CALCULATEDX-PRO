Titre : fix: isoler les historiques anonymes par visiteur

Base : main
Branche : fix/p0-anonymous-history-isolation

Chaque session anonyme dispose désormais de son historique et de ses statistiques.
Auparavant, un visiteur pouvait consulter les calculs des autres et supprimer une
opération par son identifiant. Toutes les lectures SQL, les compteurs de pagination
et les agrégations sont maintenant filtrés par visitor_id. La suppression utilise
simultanément l'identifiant du calcul et celui du visiteur ; une opération étrangère
renvoie le même HTTP 404 qu'une opération inexistante.

Les calculs HTML et API prennent leur propriétaire dans la session Flask signée,
indépendamment des champs fournis dans la requête. Les écritures exigent un
propriétaire explicite. Les tests existants ont été adaptés sans retirer leurs
assertions métier, numériques, CSRF ou de gestion des erreurs SQLite HTTP 500.

La migration nullable et son index sont conservés. Un test exécute plusieurs fois
l'initialisation d'une ancienne base et vérifie les valeurs exactes, les identifiants
et les lignes NULL. Ces lignes restent stockées, invisibles et non supprimables
par les visiteurs. Toutes les bases manipulées par les tests sont temporaires.

Validation locale :

- python -B -m unittest discover -s tests -v : 68 tests, OK (4.157 s).
- python -B -m py_compile app.py models.py database.py : code de sortie 0.
- git diff --check : code de sortie 0, aucune erreur.

Les six nouveaux tests couvrent deux clients Flask indépendants, les lectures
complètes et paginées, les filtres combinés, les statistiques HTML/API, les quatre
opérations HTML/API, les tentatives d'attribution à autrui, le CSRF, la suppression
croisée, les anciennes données et la migration idempotente.

Limites : l'identité suit le cookie de session anonyme. Effacer ce cookie ou changer
la clé secrète fait perdre l'accès à l'historique correspondant. Deux personnes
partageant le même cookie partagent la même identité. Les anciennes lignes NULL
ne sont pas réattribuées automatiquement.

Publication : document préparatoire local. Après accord explicite, pousser la
branche de correction et ouvrir une PR vers main. Aucune fusion autorisée.
