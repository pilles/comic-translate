"""Contexte SSL de repli pour les téléchargements de modèles (fork, F1).

Corrige `SSL: CERTIFICATE_VERIFY_FAILED` quand le Python géré par `uv` ne
trouve pas les racines de confiance de macOS, sans jamais désactiver la
vérification des certificats. Voir specs/01-socle-fork-ollama.md §2.

Priorité (la première condition vraie l'emporte) :
1. `SSL_CERT_FILE` ou `SSL_CERT_DIR` défini dans l'environnement -> None
   (l'utilisateur a explicitement choisi son magasin, on ne touche à rien).
2. Le magasin système par défaut existe (cafile ou capath) -> None
   (comportement historique de `urlopen`, inchangé).
3. `certifi` est installé -> contexte `ssl.create_default_context` basé sur
   `certifi.where()`.
4. Sinon -> None (aucun contexte à proposer, `urlopen` gardera son
   comportement par défaut).

Aucun chemin ne modifie `verify_mode` ou `check_hostname` : il n'y a pas de
mode où ce module produit un contexte `CERT_NONE`.
"""

from __future__ import annotations

import logging
import os
import ssl

logger = logging.getLogger(__name__)

# Mémoïsation : le résultat ne dépend que de l'environnement et du système de
# fichiers au démarrage du processus, inutile de le recalculer à chaque appel.
_cache_populated = False
_cached_context: ssl.SSLContext | None = None


def reset_cache() -> None:
    """Réinitialise le cache mémoïsé (réservé aux tests)."""
    global _cache_populated, _cached_context
    _cache_populated = False
    _cached_context = None


def get_ssl_context() -> ssl.SSLContext | None:
    """Renvoie un contexte SSL de repli, ou None pour garder le comportement par défaut."""
    global _cache_populated, _cached_context
    if _cache_populated:
        return _cached_context

    _cached_context = _build_context()
    _cache_populated = True
    return _cached_context


def _build_context() -> ssl.SSLContext | None:
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return None

    paths = ssl.get_default_verify_paths()
    system_cafile_present = bool(paths.openssl_cafile) and os.path.isfile(
        paths.openssl_cafile
    )
    system_capath_present = bool(paths.openssl_capath) and os.path.isdir(
        paths.openssl_capath
    )
    if system_cafile_present or system_capath_present:
        return None

    try:
        import certifi
    except ImportError:
        return None

    logger.info("Magasin de certificats système introuvable, repli sur certifi.")
    return ssl.create_default_context(cafile=certifi.where())
