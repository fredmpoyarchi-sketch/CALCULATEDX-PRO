"use strict";

document.querySelectorAll(".history-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (!window.confirm("Voulez-vous vraiment supprimer ce calcul ?")) {
            event.preventDefault();
        }
    });
});
