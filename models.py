class Calculatrice:

    def __init__(self):
        self._historique = []

    def _ajouter_historique(self,a, operateur, b, resultat):
        calcul = f"{a} {operateur} {b} = {resultat}"
        self._historique.append(calcul)

    def obtenir_historique(self):
        return self._historique

    def additionner(self, a, b):
        resultat = a + b
        self._ajouter_historique(a, "+", b, resultat    )
        return resultat

    def soustraire(self, a, b):
        resultat = a - b
        self._ajouter_historique(a, "-", b, resultat)
        return resultat

    def multiplier(self, a, b):
        resultat = a * b
        self._ajouter_historique(a, "*", b, resultat)
        return resultat
    
    def diviser(self, a, b):
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
        print(calculatrice._historique)

    except ValueError as e:
        print(f"Erreur: {e}")

