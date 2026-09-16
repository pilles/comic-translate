"""Utilitaires partagés entre les bancs `tools/bench_*.py`.

Code du fork (pas de `# fork:` : ce n'est pas un fichier d'origine).
"""

from __future__ import annotations

from typing import Any

# Caractères qui, en tête de cellule CSV, sont interprétés comme une formule
# par Excel/LibreOffice/Google Sheets (injection CSV, cf. OWASP). Toute cellule
# provenant d'une source non fiable (page de BD, réponse HTTP, bloc détecté...)
# doit être neutralisée avant écriture, pas seulement les colonnes "sensibles".
CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralise une cellule CSV pouvant être interprétée comme une formule.

    Préfixe d'une apostrophe pour forcer une lecture en texte brut (cf. OWASP
    CSV Injection) si la valeur est une chaîne commençant par un déclencheur.
    """
    if isinstance(value, str) and value.startswith(CSV_FORMULA_TRIGGERS):
        return "'" + value
    return value
