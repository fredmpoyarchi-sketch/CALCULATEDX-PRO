import sqlite3
from math import isfinite
from contextlib import closing
from pathlib import Path
from datetime import date

# Emplacement de la base de données
DB_PATH = Path(__file__).resolve().parent / "calculatedx.db"


def obtenir_connexion():
    """Ouvre une connexion à la base SQLite."""
    connexion = sqlite3.connect(DB_PATH)
    connexion.row_factory = sqlite3.Row
    return connexion



def initialiser_base():
    """Crée la table et ajoute la colonne visitor_id si nécessaire."""

    with closing(obtenir_connexion()) as connexion:
        with connexion:
            connexion.execute("BEGIN")
            connexion.execute("""
                CREATE TABLE IF NOT EXISTS calculs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre1 REAL NOT NULL,
                    operation TEXT NOT NULL,
                    nombre2 REAL NOT NULL,
                    resultat REAL NOT NULL,
                    date_creation TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migration non destructive des anciennes bases SQLite.
            colonnes = {
                ligne[1]
                for ligne in connexion.execute("PRAGMA table_info(calculs)")
            }

            if "visitor_id" not in colonnes:
                connexion.execute(
                    "ALTER TABLE calculs ADD COLUMN visitor_id TEXT"
                )

            connexion.execute("""
                CREATE INDEX IF NOT EXISTS idx_calculs_visitor_id
                ON calculs (visitor_id)
            """)

def enregistrer_calcul(nombre1, operation, nombre2, resultat, visitor_id):
    """Enregistre un calcul pour un visiteur anonyme."""

    if not isinstance(visitor_id, str) or not visitor_id:
        raise ValueError("Identifiant du visiteur obligatoire.")

    with closing(obtenir_connexion()) as connexion:
        with connexion:
            connexion.execute(
                """
                INSERT INTO calculs
                (nombre1, operation, nombre2, resultat, visitor_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (nombre1, operation, nombre2, resultat, visitor_id)
            )

def lire_historique(visitor_id):
    """Récupère les calculs détaillés depuis SQLite."""

    with closing(obtenir_connexion()) as connexion:
        lignes = connexion.execute(
            """
            SELECT
                id,
                nombre1,
                operation,
                nombre2,
                resultat,
                date_creation
            FROM calculs
            WHERE visitor_id = ?
            ORDER BY id DESC
            """, (visitor_id,)
        ).fetchall()

    return [dict(ligne) for ligne in lignes]


def lire_historique_pagine(visitor_id, page=1, taille=20, recherche="", operation="",
                          date_debut="", date_fin="", tri="recent") -> dict:
    """Retourne une page filtrée, avec journées SQLite UTC et tri chronologique stable."""
    if not isinstance(taille, int) or isinstance(taille, bool) or taille < 1:
        raise ValueError("La taille de page doit être un entier positif.")
    try:
        page = max(1, int(page))
    except (TypeError, ValueError, OverflowError):
        page = 1
    if operation not in ("", "+", "-", "*", "/"):
        raise ValueError("Filtre d'opération non valide.")
    ordres = {"recent": "julianday(date_creation) DESC, id DESC",
              "ancien": "julianday(date_creation) ASC, id ASC"}
    if tri not in ordres:
        raise ValueError("Tri non valide.")
    for valeur in (date_debut, date_fin):
        if valeur:
            try:
                valide = date.fromisoformat(valeur).isoformat() == valeur
            except (ValueError, TypeError):
                valide = False
            if not valide:
                raise ValueError("Date non valide : utilisez YYYY-MM-DD.")
    if date_debut and date_fin and date_debut > date_fin:
        raise ValueError("La date de début doit précéder la date de fin.")
    recherche = recherche.strip()
    criteres, parametres = ["visitor_id = ?"], [visitor_id]
    if date_debut:
        criteres.append("DATE(date_creation) >= ?")
        parametres.append(date_debut)
    if date_fin:
        criteres.append("DATE(date_creation) <= ?")
        parametres.append(date_fin)
    if recherche:
        # Recherche littérale : %, _ et les guillemets ne sont pas des jokers SQL.
        colonnes = ("nombre1", "nombre2", "resultat")
        recherche_sql = [f"instr(CAST({colonne} AS TEXT), ?) > 0" for colonne in colonnes]
        parametres.extend([recherche] * 3)
        try:
            nombre = float(recherche)
        except ValueError:
            nombre = None
        if nombre is not None and isfinite(nombre):
            recherche_sql.extend(f"{colonne} = ?" for colonne in colonnes)
            parametres.extend([nombre] * 3)
        criteres.append("(" + " OR ".join(recherche_sql) + ")")
    if operation:
        criteres.append("operation = ?")
        parametres.append(operation)
    clause = " WHERE " + " AND ".join(criteres) if criteres else ""
    with closing(obtenir_connexion()) as connexion:
        with connexion:
            connexion.execute("BEGIN")
            total = connexion.execute("SELECT COUNT(*) FROM calculs" + clause, parametres).fetchone()[0]
            pages = max(1, (total + taille - 1) // taille)
            page = min(page, pages)
            lignes = connexion.execute(
                """SELECT id, nombre1, operation, nombre2, resultat, date_creation
                FROM calculs""" + clause + " ORDER BY " + ordres[tri] + " LIMIT ? OFFSET ?",
                [*parametres, taille, (page - 1) * taille],
            ).fetchall()
    return {"calculs": [dict(ligne) for ligne in lignes], "total": total,
            "page": page, "pages": pages, "taille": taille,
            "recherche": recherche, "operation": operation,
            "date_debut": date_debut, "date_fin": date_fin, "tri": tri}


def obtenir_statistiques(visitor_id) -> dict:
    """Agrège les calculs enregistrés ; les jours sont les dates SQLite (UTC)."""
    with closing(obtenir_connexion()) as connexion:
        # Un même instantané pour les trois agrégations, même en cas d'écriture concurrente.
        with connexion:
            connexion.execute("BEGIN")
            total = connexion.execute("SELECT COUNT(*) FROM calculs WHERE visitor_id = ?", (visitor_id,)).fetchone()[0]
            par_operation = connexion.execute(
                """
                SELECT operation, COUNT(*) AS total
                FROM calculs
                WHERE visitor_id = ?
                GROUP BY operation
                ORDER BY operation
                """, (visitor_id,)
            ).fetchall()
            par_jour = connexion.execute(
                """
                SELECT DATE(date_creation) AS jour, COUNT(*) AS total
                FROM calculs
                WHERE visitor_id = ?
                GROUP BY DATE(date_creation)
                ORDER BY jour
                """, (visitor_id,)
            ).fetchall()
    return {
        "total": total,
        "par_operation": [dict(ligne) for ligne in par_operation],
        "par_jour": [dict(ligne) for ligne in par_jour],
    }


def supprimer_calcul(calcul_id, visitor_id):
    """Supprime un calcul à partir de son identifiant."""

    with closing(obtenir_connexion()) as connexion:
        with connexion:
            curseur = connexion.execute(
                """
                DELETE FROM calculs
                WHERE id = ? AND visitor_id = ?
                """,
                (calcul_id, visitor_id)
            )
            supprime = curseur.rowcount > 0
        return supprime
