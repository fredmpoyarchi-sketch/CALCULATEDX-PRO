import sqlite3
from math import isfinite
from contextlib import closing
from pathlib import Path

# Emplacement de la base de données
DB_PATH = Path(__file__).resolve().parent / "calculatedx.db"


def obtenir_connexion():
    """Ouvre une connexion à la base SQLite."""
    connexion = sqlite3.connect(DB_PATH)
    connexion.row_factory = sqlite3.Row
    return connexion


def initialiser_base():
    """Crée la table des calculs si elle n'existe pas."""

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


def enregistrer_calcul(nombre1, operation, nombre2, resultat):
    """Enregistre une opération dans SQLite."""

    with closing(obtenir_connexion()) as connexion:
        with connexion:
            connexion.execute(
                """
                INSERT INTO calculs
                (nombre1, operation, nombre2, resultat)
                VALUES (?, ?, ?, ?)
                """,
                (nombre1, operation, nombre2, resultat)
            )


def lire_historique():
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
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(ligne) for ligne in lignes]


def lire_historique_pagine(page=1, taille=20, recherche="", operation="") -> dict:
    """Retourne une page bornée ; les identifiants décroissants fixent l'ordre d'insertion."""
    if not isinstance(taille, int) or isinstance(taille, bool) or taille < 1:
        raise ValueError("La taille de page doit être un entier positif.")
    try:
        page = max(1, int(page))
    except (TypeError, ValueError, OverflowError):
        page = 1
    if operation not in ("", "+", "-", "*", "/"):
        raise ValueError("Filtre d'opération non valide.")
    recherche = recherche.strip()
    criteres, parametres = [], []
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
                FROM calculs""" + clause + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [*parametres, taille, (page - 1) * taille],
            ).fetchall()
    return {"calculs": [dict(ligne) for ligne in lignes], "total": total,
            "page": page, "pages": pages, "taille": taille,
            "recherche": recherche, "operation": operation}


def obtenir_statistiques() -> dict:
    """Agrège les calculs enregistrés ; les jours sont les dates SQLite (UTC)."""
    with closing(obtenir_connexion()) as connexion:
        # Un même instantané pour les trois agrégations, même en cas d'écriture concurrente.
        with connexion:
            connexion.execute("BEGIN")
            total = connexion.execute("SELECT COUNT(*) FROM calculs").fetchone()[0]
            par_operation = connexion.execute(
                """
                SELECT operation, COUNT(*) AS total
                FROM calculs
                GROUP BY operation
                ORDER BY operation
                """
            ).fetchall()
            par_jour = connexion.execute(
                """
                SELECT DATE(date_creation) AS jour, COUNT(*) AS total
                FROM calculs
                GROUP BY DATE(date_creation)
                ORDER BY jour
                """
            ).fetchall()
    return {
        "total": total,
        "par_operation": [dict(ligne) for ligne in par_operation],
        "par_jour": [dict(ligne) for ligne in par_jour],
    }


def supprimer_calcul(calcul_id):
    """Supprime un calcul à partir de son identifiant."""

    with closing(obtenir_connexion()) as connexion:
        with connexion:
            curseur = connexion.execute(
                """
                DELETE FROM calculs
                WHERE id = ?
                """,
                (calcul_id,)
            )
            supprime = curseur.rowcount > 0
        return supprime
