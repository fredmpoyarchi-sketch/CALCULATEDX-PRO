from math import isfinite
from decimal import Decimal, InvalidOperation

from database import (
    initialiser_base,
    enregistrer_calcul,
    lire_historique,
    lire_historique_pagine
)

def normaliser_nombre(valeur):
    """Convertit en binary64 fini ; une entrée entière ne doit perdre aucun bit."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, str)):
        raise ValueError("Une valeur numérique est requise.")
    try:
        nombre = float(valeur)
    except (ValueError, OverflowError):
        raise ValueError("Le nombre doit être représentable en flottant fini.") from None
    if not isfinite(nombre):
        raise ValueError("Le nombre doit être fini.")
    if isinstance(valeur, int) and nombre != valeur:
        raise ValueError("Cet entier ne peut pas être représenté sans perte en flottant.")
    if isinstance(valeur, str) and valeur.strip().lstrip('+-').isdigit():
        try:
            decimal = Decimal(valeur)
        except InvalidOperation:
            raise ValueError("Une valeur numérique est requise.") from None
        if decimal == decimal.to_integral_value() and Decimal.from_float(nombre) != decimal:
            raise ValueError("Cet entier ne peut pas être représenté sans perte en flottant.")
    return nombre


class Calculatrice:

    def __init__(self):
        initialiser_base()

    def _ajouter_historique(self, a, operateur, b, resultat):
        try:
            fini = isfinite(resultat)
        except OverflowError:
            fini = False
        if not fini:
            raise ValueError("Le résultat doit être un nombre fini.")
        enregistrer_calcul(a, operateur, b, resultat)

    def obtenir_historique(self):
        return lire_historique()

    def obtenir_historique_pagine(self, page=1, recherche="", operation="",
                                  date_debut="", date_fin="", tri="recent"):
        return lire_historique_pagine(page, recherche=recherche, operation=operation,
                                     date_debut=date_debut, date_fin=date_fin, tri=tri)

    def additionner(self, a, b):
        a, b = normaliser_nombre(a), normaliser_nombre(b)
        resultat = a + b
        self._ajouter_historique(a, "+", b, resultat)
        return resultat

    def soustraire(self, a, b):
        a, b = normaliser_nombre(a), normaliser_nombre(b)
        resultat = a - b
        self._ajouter_historique(a, "-", b, resultat)
        return resultat

    def multiplier(self, a, b):
        a, b = normaliser_nombre(a), normaliser_nombre(b)
        resultat = a * b
        self._ajouter_historique(a, "*", b, resultat)
        return resultat
    
    def diviser(self, a, b):
        a, b = normaliser_nombre(a), normaliser_nombre(b)
        if b == 0:
            raise ValueError("Division par zéro non autorisée.")

        resultat = a / b
        self._ajouter_historique(a, "/", b, resultat)
        return resultat

if __name__ == "__main__":
    calculatrice = Calculatrice()

    try :
        resultat1 = calculatrice.additionner(10, 5)
        resultat2 = calculatrice.soustraire(10, 5)
        resultat3 = calculatrice.multiplier(10, 5)
        resultat4 = calculatrice.diviser(10, 5)

        print(resultat1)
        print(resultat2)
        print(resultat3)
        print(resultat4)
        print(calculatrice.obtenir_historique())

    except ValueError as e:
        print(f"Erreur: {e}")

