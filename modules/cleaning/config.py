"""Réglages du nettoyage additionnel (N1 remplissage uni + N2 protection des traits).

Voir `specs/02-nettoyage-legendes.md`. Module pur : aucun import Qt ni pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CleaningConfig:
    """Config immuable, sûre à partager entre le thread worker et l'UI.

    `INERT` (décoché) doit produire un comportement strictement identique à
    l'app d'origine (`clean_page` court-circuite tout traitement). `UI_DEFAULTS`
    porte les valeurs initiales de la conception (specs/02 §3-4), à affiner
    par `tools/bench_cleaning.py --sweep` et la revue visuelle de Philippe.
    """

    # --- Réglages exposés dans Réglages > Outils > Image Cleaning ---
    uniform_fill: bool = False
    protect_lines: bool = False
    free_dilate_iterations: int = 3

    # --- N1 : remplissage uni (anneau autour de chaque composante éligible) ---
    ring_inner: int = 2
    ring_outer: int = 8
    ring_min_pixels: int = 200
    color_tolerance: int = 12
    uniform_share: float = 0.85
    core_ratio_max: float = 0.90
    ring_quadrant_max: float = 10.0
    # Largeur du fondu (feathering) appliqué au bord du remplissage uni.
    feather_px: int = 3

    # --- N2 : protection des traits (bords de case) ---
    line_length: int = 61  # L_h = L_v ; doit être impair (cf. __post_init__)
    line_dark_max: int = 128
    line_halo: int = 2
    line_max_thickness: int = 7  # T : sépare un trait fin d'un aplat épais
    line_band_margin: int = 69  # >= line_length / 2 (cf. __post_init__)
    # Jalon 2 (critic pass2 consigne 6/7) : "components" = top-hat morphologique
    # par composantes connexes (généralise aux traits non-axiaux : cadre ondulé,
    # incliné) ; "runs" = ancien algorithme run_ge, inchangé, conservé pour mesure
    # comparée (`--n2-impl`) et comme filet de secours explicite (jamais choisi
    # automatiquement : le plafond de saturation n'y replie plus, consigne 5).
    line_detector: str = "components"
    # Part minimale (hors masque courant) exigée d'une composante fine candidate
    # pour être protégée : distingue un bord de case (qui déborde largement de la
    # zone de texte) d'un jambage de lettre (entièrement contenu dans le masque).
    line_outside_min: float = 0.10
    # Plafond de saturation (consigne 5) : au-delà, protection ABANDONNÉE sur la
    # bande (jamais de repli vers "runs", qui protège davantage, pas moins).
    line_max_protected_share: float = 0.35

    # --- Exclusion des bulles de l'anneau N1 (critic pass2 consigne #4) ---
    # Documenté, non corrigé (critic pass2 consigne 12) : l'hypothèse "bbox ±
    # bubble_ring_exclusion contient le masque bulle" n'est vraie que pour une
    # marge <= 3 ; en flux manuel, `generate_mask_from_strokes` redilate le
    # masque (noyau 5x5 x `free_dilate_iterations`) — dès iterations >= 4
    # (+20 px), le résidu de masque bulle peut déborder de cette zone de 7 px,
    # avec un risque de fuite dans l'anneau N1 d'une composante voisine.
    bubble_ring_exclusion: int = 7
    # Fraction max de recouvrement core/zone-ou-graine-bulle tolérée avant de
    # traiter une composante comme trop proche d'une bulle (consigne 1 et
    # "bulle_proche" en fraction, jalon 2).
    bubble_overlap_max: float = 0.20
    # Dilatation (px) du contour de bulle (`build_bubble_clip_mask`) pour couvrir
    # l'encre du contour sur tout son périmètre, angles compris (consigne 2) ;
    # calibrée sur l'épaisseur de trait typique d'un contour de bulle.
    bubble_interior_dilation: int = 4

    def __post_init__(self) -> None:
        # ValueError (pas assert) : les asserts disparaissent sous python -O,
        # ces invariants doivent tenir même en production (sécurité mineure #7).
        if self.line_length % 2 != 1:
            raise ValueError(
                f"line_length doit être impair (reçu {self.line_length}) : "
                "l'équivalence run_ge <-> OPEN(ones(1,L)) n'est garantie que pour L impair."
            )
        if self.line_band_margin < self.line_length / 2:
            raise ValueError(
                f"line_band_margin ({self.line_band_margin}) doit être >= line_length/2 "
                f"({self.line_length / 2}) pour que la bande couvre le noyau d'ouverture."
            )
        if self.line_detector not in ("components", "runs"):
            raise ValueError(
                f"line_detector doit valoir 'components' ou 'runs' (reçu {self.line_detector!r})"
            )


# Décoché : comportement strictement identique à l'app d'origine.
INERT = CleaningConfig(uniform_fill=False, protect_lines=False, free_dilate_iterations=3)

# Valeurs initiales de la conception, cochées par défaut dans l'UI. Le jeu
# candidat suggéré par le banc `--sweep` est consigné dans le rendu de
# l'implementer (JOURNAL / réponse), pas ici : Philippe tranche sur planche.
UI_DEFAULTS = CleaningConfig(uniform_fill=True, protect_lines=True, free_dilate_iterations=3)


def is_inert(cfg: CleaningConfig) -> bool:
    """True si ni N1 (`uniform_fill`) ni N2 (`protect_lines`) ne sont demandés.

    Ne couvre QUE ces deux réglages : `clean_page` est alors un passe-plat vers
    `bubble_cleanup`, sans passer par N1/N2. `free_dilate_iterations` n'entre
    PAS dans ce calcul — une marge != 3 modifie déjà le masque produit par
    `generate_mask` (dilatation) avant même d'atteindre `clean_page`, y compris
    quand les deux cases sont décochées.
    """
    return not cfg.uniform_fill and not cfg.protect_lines
