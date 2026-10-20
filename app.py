import os
import secrets
import sqlite3

from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from models import Calculatrice
from database import obtenir_statistiques, supprimer_calcul

app = Flask(__name__)
app.secret_key = os.environ.get("CALCULATEDX_SECRET_KEY")
if not app.secret_key or not app.secret_key.strip():
    raise RuntimeError(
        "Démarrage impossible : définissez CALCULATEDX_SECRET_KEY avec une clé "
        "secrète aléatoire persistante dans l'environnement."
    )
calculatrice = Calculatrice()


@app.context_processor
def fournir_jeton_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return {"csrf_token": session["csrf_token"]}


@app.before_request
def verifier_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None

    attendu = session.get("csrf_token")
    fourni = request.headers.get("X-CSRF-Token")
    if fourni is None and request.endpoint != "api_calculer":
        fourni = request.form.get("csrf_token")
    if (
        not isinstance(attendu, str)
        or not isinstance(fourni, str)
        or not secrets.compare_digest(attendu.encode("utf-8"), fourni.encode("utf-8"))
    ):
        message = "Jeton CSRF absent ou invalide. Rechargez la page et réessayez."
        if request.endpoint == "api_calculer":
            return jsonify({"erreur": message}), 400
        return message, 400
    return None


@app.route("/")
def accueil():
    return render_template("index.html")


@app.route("/calcul", methods=["GET", "POST"])
def calcul():
    from math import isfinite

    resultat = None
    erreur = None

    if request.method == "POST":
        try:
            nombres = []
            for champ, libelle in (
                ("nombre1", "premier nombre"),
                ("nombre2", "deuxième nombre"),
            ):
                valeur = request.form.get(champ, "").strip()
                if not valeur:
                    raise ValueError(f"Veuillez saisir le {libelle}.")
                try:
                    nombre = float(valeur)
                except ValueError:
                    raise ValueError(
                        f"Le {libelle} doit être une valeur numérique valide."
                    ) from None
                if not isfinite(nombre):
                    raise ValueError(f"Le {libelle} doit être un nombre fini.")
                nombres.append(nombre)

            nombre1, nombre2 = nombres
            operation = request.form.get("operation", "")

            if operation == "addition":
                resultat = calculatrice.additionner(nombre1, nombre2)

            elif operation == "soustraction":
                resultat = calculatrice.soustraire(nombre1, nombre2)

            elif operation == "multiplication":
                resultat = calculatrice.multiplier(nombre1, nombre2)

            elif operation == "division":
                resultat = calculatrice.diviser(nombre1, nombre2)

            else:
                raise ValueError("Opération non valide. Choisissez une opération proposée.")

        except ValueError as e:
            erreur = str(e)

    return render_template(
        "calcul.html",
        resultat=resultat,
        erreur=erreur
    ), 400 if erreur else 200

@app.route("/historique")
def historique():
    operations = calculatrice.obtenir_historique()

    return render_template(
        "historique.html",
        historique=operations
    )


@app.route("/historique/supprimer/<int:calcul_id>", methods=["POST"])
def supprimer_operation(calcul_id):

    if not supprimer_calcul(calcul_id):
        return "Calcul introuvable : aucune opération ne correspond à cet identifiant.", 404

    return redirect(url_for("historique"))


@app.route("/api/v1/calculer", methods=["POST"])
def api_calculer():
    from math import isfinite

    if not request.is_json:
        return jsonify({
            "erreur": "Le corps de la requête doit être au format JSON."
        }), 400

    donnees = request.get_json(silent=True)
    if not isinstance(donnees, dict):
        return jsonify({
            "erreur": "Le corps de la requête doit être un objet JSON valide."
        }), 400

    champs_manquants = [
        champ for champ in ("nombre1", "operation", "nombre2")
        if champ not in donnees
    ]
    if champs_manquants:
        return jsonify({
            "erreur": "Champs obligatoires manquants : " + ", ".join(champs_manquants) + "."
        }), 400

    for champ in ("nombre1", "nombre2"):
        nombre = donnees[champ]
        if isinstance(nombre, bool) or not isinstance(nombre, (int, float)):
            return jsonify({
                "erreur": f"Le champ {champ} doit être un nombre JSON, sans booléen."
            }), 400
        try:
            fini = isfinite(nombre)
        except OverflowError:
            fini = False
        if not fini:
            return jsonify({
                "erreur": f"Le champ {champ} doit être un nombre fini représentable."
            }), 400

    nombre1 = donnees["nombre1"]
    operation = donnees["operation"]
    nombre2 = donnees["nombre2"]

    if not isinstance(operation, str) or operation not in (
        "addition", "soustraction", "multiplication", "division"
    ):
        return jsonify({
            "erreur": "Opération non valide."
        }), 400

    try:
        if operation == "addition":
            resultat = calculatrice.additionner(nombre1, nombre2)

        elif operation == "soustraction":
            resultat = calculatrice.soustraire(nombre1, nombre2)

        elif operation == "multiplication":
            resultat = calculatrice.multiplier(nombre1, nombre2)

        elif operation == "division":
            resultat = calculatrice.diviser(nombre1, nombre2)
    except ValueError as e:
        return jsonify({
            "erreur": str(e)
        }), 400

    return jsonify({
        "resultat": resultat
    }), 200

@app.route("/statistiques", methods=["GET"])
def statistiques():
    try:
        donnees = obtenir_statistiques()
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de la lecture du tableau de bord.")
        return render_template("statistiques.html", statistiques=None), 500
    dominante = max(donnees["par_operation"], key=lambda ligne: ligne["total"], default=None)
    maximum_journalier = max((ligne["total"] for ligne in donnees["par_jour"]), default=1)
    return render_template("statistiques.html", statistiques=donnees,
                           dominante=dominante, maximum_journalier=maximum_journalier)


@app.route("/api/v1/statistiques", methods=["GET"])
def api_statistiques():
    try:
        return jsonify(obtenir_statistiques()), 200
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de la lecture des statistiques.")
        return jsonify({"erreur": "Impossible de récupérer les statistiques."}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
