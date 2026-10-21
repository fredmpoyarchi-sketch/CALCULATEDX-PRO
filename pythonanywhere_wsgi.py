"""À importer comme application depuis le fichier WSGI de l'onglet Web."""

from pythonanywhere_config import create_application

application = create_application()
