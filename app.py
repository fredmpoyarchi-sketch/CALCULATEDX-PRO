from flask import Flask, render_template, request, jsonify
from models import Calculatrice

app = Flask(__name__)
calculatrice = Calculatrice()


@app.route("/")
def accueil():
    return render_template("index.html")


@app.route("/calcul", methods=["GET", "POST"])
def calcul():

    resultat = None
    erreur = None

    if request.method == "POST":
        nombre1 = float(request.form["nombre1"])
        operation = request.form["operation"]
        nombre2 = float(request.form["nombre2"])

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
            erreur = str(e)

    return render_template(
        "calcul.html",
        resultat=resultat,
        erreur=erreur
    )

@app.route("/historique")
def historique():
    historique_calculs = calculatrice.obtenir_historique()

    return render_template(
        "historique.html",
        historique=historique_calculs
    )

@app.route("/api/v1/calculer", methods=["POST"])
def api_calculer():
    donnees = request.get_json()

    if not donnees:
        return jsonify({
            "erreur": "Aucune donnée reçue."
        }), 400

    if "nombre1" not in donnees or "operation" not in donnees or "nombre2" not in donnees:
        return jsonify({
            "erreur": "Données manquantes. Veuillez remplir les champs manquants."
        }), 400

    nombre1 = donnees["nombre1"]
    operation = donnees["operation"]
    nombre2 = donnees["nombre2"]

    try:
        if operation == "addition":
            resultat = calculatrice.additionner(nombre1, nombre2)

        elif operation == "soustraction":
            resultat = calculatrice.soustraire(nombre1, nombre2)

        elif operation == "multiplication":
            resultat = calculatrice.multiplier(nombre1, nombre2)

        elif operation == "division":
            resultat = calculatrice.diviser(nombre1, nombre2)
        else:
            return jsonify({
                "erreur": "Opération non valide."
            }), 400
    except ValueError as e:
        return jsonify({
            "erreur": str(e)
        }), 400

    return jsonify({
        "resultat": resultat
    }), 200

if __name__ == "__main__":
    app.run(debug=True)