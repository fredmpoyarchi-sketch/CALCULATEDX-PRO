import os
import secrets
import sqlite3

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
from models import Calculatrice, normaliser_nombre
from database import obtenir_statistiques, supprimer_calcul, INITIALISER_AU_DEMARRAGE

app = Flask(__name__)
app.config.update(
    DEBUG=False,
    TESTING=False,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=16 * 1024,
)
app.secret_key = os.environ.get("CALCULATEDX_SECRET_KEY")
if not app.secret_key or not app.secret_key.strip():
    raise RuntimeError(
        "Démarrage impossible : définissez CALCULATEDX_SECRET_KEY avec une clé "
        "secrète aléatoire persistante dans l'environnement."
    )
calculatrice = Calculatrice(initialiser=INITIALISER_AU_DEMARRAGE)

@app.before_request
def limiter_corps_requete():
    # Lecture bornée et mise en cache avant le CSRF et toute écriture SQLite.
    limite = app.config["MAX_CONTENT_LENGTH"]
    if request.content_length is not None and request.content_length > limite:
        abort(413)
    # Un flux WSGI terminé peut être tronqué silencieusement à la limite.
    # Lire au plus un octet supplémentaire permet de détecter le dépassement.
    if "wsgi.input_terminated" in request.environ:
        request.max_content_length = limite + 1
    try:
        corps = request.get_data(cache=True)
    finally:
        request.max_content_length = limite
    if len(corps) > limite:
        abort(413)


@app.errorhandler(413)
def corps_requete_excessif(erreur):
    message = "Corps de requête trop volumineux (maximum 16 Kio)."
    if request.path.startswith("/api/"):
        return jsonify({"erreur": message}), 413
    return message, 413


@app.before_request
def limiter_frequence_requetes():
    # Activé uniquement par un profil de déploiement qui connaît son frontal.
    limiteur = app.extensions.get("request_rate_limiter")
    if limiteur is not None:
        attente = limiteur.retry_after(request.environ)
        if attente:
            reponse = jsonify({"erreur": "Trop de requêtes. Réessayez plus tard."})
            reponse.status_code = 429
            reponse.headers["Retry-After"] = str(attente)
            reponse.headers["Cache-Control"] = "no-store"
            return reponse
    return None


@app.after_request
def ajouter_entetes_securite(reponse):
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    reponse.headers["Referrer-Policy"] = "no-referrer"
    reponse.headers["X-Frame-Options"] = "DENY"
    reponse.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return reponse


def obtenir_visitor_id():
    """Retourne un identifiant anonyme propre à la session."""
    visitor_id = session.get("visitor_id")

    if not isinstance(visitor_id, str) or len(visitor_id) != 64:
        visitor_id = secrets.token_hex(32)
        session["visitor_id"] = visitor_id

    return visitor_id

@app.before_request
def identifier_visiteur():
    obtenir_visitor_id()

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
                    nombre = normaliser_nombre(valeur)
                except ValueError:
                    raise ValueError(
                        f"Le {libelle} doit être un nombre fini et représentable (sans perte pour les entiers)."
                    ) from None
                if not isfinite(nombre):
                    raise ValueError(f"Le {libelle} doit être un nombre fini.")
                nombres.append(nombre)

            nombre1, nombre2 = nombres
            operation = request.form.get("operation", "")

            if operation == "addition":
                resultat = calculatrice.additionner(
                    nombre1, nombre2, obtenir_visitor_id()
                )

            elif operation == "soustraction":
                resultat = calculatrice.soustraire(
                    nombre1, nombre2, obtenir_visitor_id()
                )

            elif operation == "multiplication":
                resultat = calculatrice.multiplier(
                    nombre1, nombre2, obtenir_visitor_id()
                )

            elif operation == "division":
                resultat = calculatrice.diviser(
                    nombre1, nombre2, obtenir_visitor_id()
                )

            else:
                raise ValueError("Opération non valide. Choisissez une opération proposée.")

        except ValueError as e:
            erreur = str(e)
        except sqlite3.Error:
            app.logger.exception("Erreur SQLite lors de l'enregistrement d'un calcul.")
            return render_template("calcul.html", resultat=None,
                                   erreur="Impossible d'enregistrer le calcul. Réessayez plus tard."), 500

    return render_template(
        "calcul.html",
        resultat=resultat,
        erreur=erreur
    ), 400 if erreur else 200

@app.route("/historique")
def historique():
    try:
        pagination = calculatrice.obtenir_historique_pagine(
            obtenir_visitor_id(),
            request.args.get("page", "1"), request.args.get("recherche", ""),
            request.args.get("operation", ""), request.args.get("date_debut", ""),
            request.args.get("date_fin", ""), request.args.get("tri", "recent"))
    except ValueError:
        return "Filtres non valides : vérifiez l'opération, le tri et les dates YYYY-MM-DD (début ≤ fin).", 400
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de la lecture de l'historique.")
        return "Impossible de charger l'historique. Réessayez dans quelques instants.", 500

    return render_template(
        "historique.html",
        historique=pagination["calculs"],
        pagination=pagination
    )


@app.route("/historique/supprimer/<int:calcul_id>", methods=["POST"])
def supprimer_operation(calcul_id):

    try:
        supprime = supprimer_calcul(calcul_id, obtenir_visitor_id())
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de la suppression d'un calcul.")
        return "Impossible de supprimer ce calcul. Réessayez dans quelques instants.", 500

    if not supprime:
        return "Calcul introuvable : aucune opération ne correspond à cet identifiant.", 404

    if any(champ in request.form for champ in ("page", "recherche", "operation", "date_debut", "date_fin", "tri")):
        return redirect(url_for("historique", page=request.form.get("page", "1"),
                                recherche=request.form.get("recherche", ""),
                                operation=request.form.get("operation", ""),
                                date_debut=request.form.get("date_debut", ""),
                                date_fin=request.form.get("date_fin", ""),
                                tri=request.form.get("tri", "recent")))
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
            donnees[champ] = normaliser_nombre(nombre)
        except ValueError as erreur:
            return jsonify({
                "erreur": f"Le champ {champ} est invalide : {erreur}"
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
            resultat = calculatrice.additionner(
                nombre1, nombre2, obtenir_visitor_id()
            )

        elif operation == "soustraction":
            resultat = calculatrice.soustraire(
                nombre1, nombre2, obtenir_visitor_id()
            )

        elif operation == "multiplication":
            resultat = calculatrice.multiplier(
                nombre1, nombre2, obtenir_visitor_id()
            )

        elif operation == "division":
            resultat = calculatrice.diviser(
                nombre1, nombre2, obtenir_visitor_id()
            )
    except ValueError as e:
        return jsonify({
            "erreur": str(e)
        }), 400
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de l'enregistrement d'un calcul via l'API.")
        return jsonify({"erreur": "Impossible d'enregistrer le calcul. Réessayez plus tard."}), 500

    return jsonify({
        "resultat": resultat
    }), 200

@app.route("/statistiques", methods=["GET"])
def statistiques():
    try:
        donnees = obtenir_statistiques(obtenir_visitor_id())
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
        return jsonify(obtenir_statistiques(obtenir_visitor_id())), 200
    except sqlite3.Error:
        app.logger.exception("Erreur SQLite lors de la lecture des statistiques.")
        return jsonify({"erreur": "Impossible de récupérer les statistiques."}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
