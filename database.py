import sqlite3
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

    with obtenir_connexion() as connexion:

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

        connexion.commit()


def enregistrer_calcul(nombre1, operation, nombre2, resultat):
    """Enregistre une opération dans SQLite."""

    with obtenir_connexion() as connexion:
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

    with obtenir_connexion() as connexion:
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


def supprimer_calcul(calcul_id):
    """Supprime un calcul à partir de son identifiant."""

    with obtenir_connexion() as connexion:
        curseur = connexion.execute(
            """
            DELETE FROM calculs
            WHERE id = ?
            """,
            (calcul_id,)
        )

        connexion.commit()

        return curseur.rowcount > 0