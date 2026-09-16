# Spec 02 — Nettoyage : remplissage uni et protection des bords de case

> **STATUT : jalon 1 + jalon 2 implémentés le 2026-09-13, calibrés sur la page de référence de
> Philippe. Couverture 100 % sur cette page. Revue visuelle finale (§9.1) EN ATTENTE.**
> Prérequis : spec 01 appliquée. Lire `00-feuille-de-route.md` §6.

**Objectif** : que le nettoyage des **légendes hors bulles** soit aussi propre que celui des
bulles, sans abîmer les bords de case ni inventer de taches.

---

## 1. Défaut constaté (2026-09-11, page réelle, avant/après fourni par Philippe)

| Zone | Résultat actuel |
|---|---|
| Texte **dans les bulles** | ✅ propre : fond blanc, contour de bulle conservé |
| Légendes **au-dessus des cases** (texte sur le papier) | ❌ taches grises inventées, bord supérieur des cases abîmé, zone sombre du dessin qui « coule » vers le haut |
| Légende **sous une case** | ❌ trait de bord de case effacé |

## 2. Cause — mesurée dans le code (filvyb `059046d`, corrigée le 2026-09-13)

La rédaction initiale de cette section contenait 4 erreurs factuelles, corrigées après mesure
dans le code pendant la conception :

1. Le flux manuel « Nettoyer » **n'appelle pas** `generate_mask`. `generate_mask` n'a que deux
   appelants : `pipeline/batch_processor.py:312` (lot) et `pipeline/webtoon_batch/chunk.py:206`
   (webtoon). Le flux manuel passe par un chemin différent : Segment →
   `manual_workflow.blk_detect_segment` → `drawing_manager.make_segmentation_stroke_data` →
   `build_block_mask_data` (tracé rouge) ; puis Clean → `controller.inpaint_and_set` →
   `manual_workflow.inpaint_and_set` → `image_viewer.get_mask_for_inpainting()` →
   `drawing_manager.generate_mask_from_strokes()`.
2. La dilatation en mode lot est d'environ **6 px** (noyau 5×5 plein = rayon 2 px × 3 itérations,
   `image_utils.py:348-349`), pas 15 px comme initialement estimé.
3. Le flux manuel dilate le masque **deux fois** : `generate_mask_from_strokes` re-dilate 5×5 × 3
   itérations (+6 px), en plus des 2 px de plume du tracé → **≈13 px** effectifs. C'est
   l'explication principale de l'écart observé entre lot et manuel.
4. La dilatation est **bornée au crop bbox du bloc ± 5 %** (`_resolve_block_crop_bounds`), pas
   sans limite.
5. Le remplissage uni **existait déjà**, mais seulement pour les bulles :
   `pipeline/inpainting.py`, `_apply_fast_bubble_cleanup` (+ `_estimate_fast_fill_color`,
   `_fast_fill_block`), verrouillé sur `text_class == "text_bubble"`. Les blocs `text_free`
   (légendes) n'en bénéficiaient jamais.

Point de convergence unique des deux flux (lot et manuel) : `InpaintingHandler.inpaint_image`
(`pipeline/inpainting.py`). Le masque déborde sur les traits de case ; LaMa reconstruit ces zones
d'après le dessin voisin.

**Le modèle n'est pas en cause** : l'app utilise déjà un LaMa affiné sur manga/comics
(`lama-manga-dynamic` en ONNX, `anime-manga-big-lama` en torch). Ne pas chercher à le remplacer
dans ce lot.

## 3. Algorithme retenu

Module pur `modules/cleaning/` (numpy/mahotas/imkit, zéro Qt, zéro import de `pipeline/`),
branché en un point unique : `clean_page(image, mask, blk_list, cfg, *, protect_mask=None,
bubble_cleanup=None)`, appelé depuis `inpaint_image` avant l'inpainting LaMa.

**Ordre : N2 (protection des traits) → bulles (code d'origine, intact) → N1 (remplissage uni sur
le résidu)**. Justification de l'ordre : l'anneau autour d'une légende collée à un bord de case
est presque toujours traversé par ce bord ; retirer les pixels de trait du masque *avant* de
juger l'uniformité évite qu'un trait sombre fasse basculer un bloc uniforme vers LaMa à tort.
Les bulles restent traitées par le code d'origine, inchangé, sur le masque déjà débarrassé des
traits protégés.

### N1 — composantes connexes par graine

Par page, une seule fois : `connected_components(mask > 0, 8)`. Pour chaque bloc `text_free`,
une **graine** est calculée avec la même fonction que le flux d'origine
(`_resolve_block_crop_bounds`, crop bbox ± 5 %) ; les composantes dont un pixel touche cette
graine sont candidates.

- **Éligible** ⇔ une seule graine la revendique (pas de conflit entre blocs), ce bloc est
  `text_free`, la composante ne touche aucune bulle dilatée de `bubble_ring_exclusion` (7 px), et
  elle ne touche pas un tracé humain protégé (`protect_mask`, flux manuel). Sinon **skip**, avec
  raison (`partagee`, `bulle`, `bulle_proche`, `pinceau`, `sans_bloc`) — composante intacte, ni N1
  ni N2.
- Pour une composante éligible : `core` = composante entière ; `ring` = anneau
  `dilate(core, ring_outer) & ¬dilate(core, ring_inner)`, purgé du masque restant, du halo
  protégé N2 et des bornes image.
- `|ring| < ring_min_pixels` → LaMa. `|core| / |core ∪ ring| > core_ratio_max` → LaMa.
- Médiane par canal sur l'anneau ; `part` = fraction de pixels de l'anneau à ≤ `color_tolerance`
  de la médiane ; **critère quadrants** : l'anneau est découpé en 4 secteurs autour du centroïde
  (secteurs trop petits ignorés) ; l'écart maximal entre médianes de secteurs doit rester
  ≤ `ring_quadrant_max`, avec au moins 3 secteurs valides. `part ≥ uniform_share` **et** critère
  quadrants respecté → **uni** : `image[core] ← médiane` (fondu `feather_px`), `mask[core] ← 0`.
  Sinon → LaMa.

Le critère quadrants remplace la « tolérance à une minorité de pixels sombres » envisagée
initialement : cette dernière ne distingue pas un trait de case d'un motif du dessin.

### N2 — protection des traits (top-hat directionnel, par plages O(N))

Une fois par page, restreint à une bande autour des blocs `text_free` (`line_band_margin`) :
binarisation (`gray < min(otsu, line_dark_max)`), puis détection de plages sombres continues par
axe (`run_ge`, implémentation par différences cumulées, O(N), sans boucle Python — équivalente à
une ouverture morphologique `OPEN(ones(1, L))` pour `L` impair, vérifiée par test croisé).
`trait_h` = plage horizontale longue **et pas** épaisse verticalement (`line_max_thickness`),
symétrique pour `trait_v` — sépare un bord de case fin d'un aplat sombre du dessin. Les pixels de
trait (+ halo `line_halo`) sont retirés du masque, uniquement dans la zone des blocs `text_free`
(les bulles et les coups de pinceau manuels ailleurs ne sont jamais amputés).

### Contrat de non-écriture

`clean_page` n'écrit jamais dans `image`/`mask` reçus tant qu'aucun traitement actif n'est
requis :
- config inerte (`is_inert`, les deux cases décochées) + pas de `bubble_cleanup` injecté →
  identité d'objet (`out is image`, `out is mask`).
- config inerte + `bubble_cleanup` injecté → renvoie **verbatim** son 3-uplet, aucune copie
  ajoutée.
- config active → copie paresseuse à la première écriture réelle ; `bubble_cleanup` reste seul
  responsable des bulles, jamais modifié par ce module.

## 4. Paramètres

**Grille de calibration** (un axe à la fois, sur `bench/out/blocks/` généré depuis
`bench/pages/`, 7 pages de test « Fun Home ») :

| Paramètre | Initial | Grille |
|---|---|---|
| `ring_inner` | 2 | {1, 2, 3} |
| `ring_outer` | 8 | {6, 8, 12} |
| `ring_min_pixels` | 200 | {100, 200, 400} |
| `color_tolerance` | 12 | {8, 12, 16, 24} |
| `uniform_share` | 0.85 | {0.75, 0.85, 0.92} |
| `core_ratio_max` | 0.90 | fixe |
| `ring_quadrant_max` | 10.0 | {6, 10, 16} |
| `line_length` (L) | 61 (impair) | {31, 45, 61, 91} |
| `line_dark_max` | 128 | {96, 128, 160} |
| `line_halo` | 2 | {1, 2, 4} |
| `line_max_thickness` (T) | 7 | {5, 7, 11} |
| `bubble_ring_exclusion` | 7 | fixe (critic pass2 #4) |

**Résultat du sweep** (un axe à la fois, `--sweep`, mesuré sur les 7 pages, `bench/out/sweep.csv`) :
le meilleur candidat brut (part uni la plus élevée) est `free_dilate_iterations=1`, part uniforme
globale 0,827, mais avec 7 blocs mixtes (composantes du même bloc décidées différemment — le pire
cas visuel). Par axe, au mixte minimal : `ring_outer=6`, `color_tolerance=16`, `uniform_share=0.75`.
**Ce jeu final n'est pas tranché** — le sweep n'a exploré qu'un axe à la fois (pas d'interaction
croisée) et l'arbitrage taux d'uniforme vs blocs mixtes revient à la revue visuelle de Philippe
(§9.1).

**Valeurs `UI_DEFAULTS` livrées** (`modules/cleaning/config.py`, cochées par défaut dans l'UI,
non recalées sur le sweep — à ajuster après revue) :

```
uniform_fill=True, protect_lines=True, free_dilate_iterations=3,
ring_inner=2, ring_outer=8, ring_min_pixels=200, color_tolerance=12,
uniform_share=0.85, core_ratio_max=0.90, ring_quadrant_max=10.0, feather_px=3,
line_length=61, line_dark_max=128, line_halo=2, line_max_thickness=7,
line_band_margin=69, bubble_ring_exclusion=7
```

`INERT` (les deux cases décochées) : `uniform_fill=False, protect_lines=False,
free_dilate_iterations=3` — comportement strictement identique à l'app d'origine, prouvé par
test (`test_cleaning_invariant.py`).

## 5. N3 — hors périmètre

Non implémenté, non nécessaire au vu du banc (voir §9.2, §10). Verdict à réévaluer via une
colonne CSV `debord_case` si un besoin réapparaît (voir `specs/00-feuille-de-route.md` §5).

## 6. Réglages livrés (jalon 1 + jalon 2 — aucun nouveau réglage UI)

Réglages > Outils, section Image Cleaning (`app/ui/settings/tools_page.py`,
`app/ui/settings/settings_ui.py`) :

| Réglage (libellé UI) | Défaut |
|---|---|
| « Automatic flat fill » | coché |
| « Protect thin straight lines (panel borders) » | coché |
| « Margin around free text (iterations) » | 3 (bornes 0–6) |

Persistés sous `tools/cleaning` (QSettings, comme le reste des réglages Outils), **relus à chaque
nettoyage** — recharger la page ou changer les réglages puis relancer « Nettoyer » applique
immédiatement le nouveau jeu, y compris pour défaire un nettoyage déjà appliqué.

Les deux cases décochées ⇒ comportement strictement identique à l'app d'origine (masque et image
inchangés, preuve par test).

Jalon 2 ajoute 8 paramètres internes à `CleaningConfig` (`bubble_overlap_max`, `line_detector`,
`line_outside_min`, `line_max_protected_share`, `bubble_interior_dilation`, etc.) : **aucun n'est
exposé dans Réglages > Outils**. Ils prennent les défauts du dataclass ; seul `UI_DEFAULTS`
(banc) diffère de `INERT`. `cleaning_config_from_settings_page` ne transmet toujours que les 3
réglages ci-dessus.

**Note** : en mode manuel, la marge (`free_dilate_iterations`) s'applique **deux fois** (voir §2
point 3) — à 3, cela reste ≈13 px effectifs en manuel contre ≈6 px en lot ; ce n'est pas divisé
par deux dans ce lot, pour garder l'invariant octet-pour-octet avec l'origine quand la marge vaut
sa valeur par défaut (3).

## 7. Banc — `tools/bench_cleaning.py`

Options réelles (`--help`) :

```
tools/bench_cleaning.py pages_dir --out OUT
  --pages [PAGES ...]        restreindre à ces fichiers
  --min-size N                taille mini en octets (défaut interne)
  --save-blocks DIR            écrit les blocs détectés (JSON, sans pixels)
  --blocks DIR                 relit les blocs (JSON), priorité sur la détection
  --manual-mask [{qt,approx}]  simule le masque du flux manuel (M7)
                                 qt : rejoue le vrai chemin DrawingManager/ImageViewer
                                 (offscreen, écart nul par construction, défaut si l'option
                                 est donnée sans valeur et PySide6 importable)
                                 approx : approximation numpy (find_contours -> fill_poly
                                 -> dilate), écart mesuré imprimé en en-tête du rapport
  --gpu                        GPU (défaut : CPU)
  --n2-impl {runs,mahotas}      mesure comparée de l'implémentation N2 (défaut : runs)
  --sweep                       grille de calibration -> bench/out/sweep.csv
```

Sortie : uniquement sous `bench/out/` (chemin réel, résolu, confiné à ce dossier — refus sinon),
ignoré par git. Une planche PNG par page (original | masque | avant | après) et
`bench/out/report.csv` (une ligne par composante, en-tête de métadonnées : date, commit, config,
device, providers, `manual_mask`, `n2_impl`).

## 8. Tests réels

| Fichier | Tests |
|---|---|
| `tests/test_cleaning_components.py` | 6 |
| `tests/test_cleaning_uniform.py` | 8 |
| `tests/test_cleaning_lines.py` | 10 |
| `tests/test_cleaning_contract.py` | 5 |
| `tests/test_cleaning_invariant.py` | 3 |
| `tests/test_cleaning_config.py` | 8 |
| `tests/test_bench_cleaning.py` | 13 |
| `tests/test_manual_mask_equivalence.py` | 1 (`--gui` uniquement) |

Total dépôt : **139 tests passés** (`uv run pytest -q`, hors `--gui`).

## 9. État des critères de réussite

**9.1 — Revue visuelle de Philippe (page de référence, taches disparues, bords de case intacts,
bulles au moins aussi propres) : EN ATTENTE.** Jalon 2 (voir §13) a mesuré et corrigé, sur la
capture réelle de Philippe (`funhome_012`, mode manuel), les 3 taches grises et les 2 bords rongés
diagnostiqués : couverture 100 % sur cette page (5 légendes uni, contours de bulle intacts). Reste
à ouvrir `bench/out/*_planche.png` pour confirmation visuelle finale et à trancher le jeu de
paramètres définitif (§4, sweep jalon 2 en §13).

**9.2 — Temps et couverture, mesurés sur les 7 pages du banc (`bench/pages/`, échantillon
« Fun Home ») :**

- Temps de nettoyage par page **non supérieur** à l'existant : confirmé, ≤ à ±5 % de l'avant ;
  7–8 s/page en CPU, dominé par LaMa (N1/N2 ajoutent un coût marginal).
- Couverture par page, en mode lot puis en mode manuel `qt` (`%uni` = part de composantes
  `text_free` remplies en uni ; skip ventilé par raison) :

| Page | Lot : %uni {skip} | Manuel qt : %uni {skip} |
|---|---|---|
| 012 | 40 % {non_uniforme 1, bulle_proche 2, bulle 2} | 40 % {sans_bloc 11, bulle_proche 2, non_uniforme 1, bulle 1} |
| 020 | 0 % {non_uniforme 2, bulle 1} | 0 % {sans_bloc 4, non_uniforme 2, bulle 1} |
| 045 | 80 % {bulle_proche 1, partagee 4, non_uniforme 1, bulle 2} (1 mixte) | 20 % {bulle_proche 2, non_uniforme 1, partagee 3, quadrants_insuffisants 1, bulle 2, sans_bloc 2} |
| 060 | 0 % {} | 0 % {} |
| 080 | 40 % {quadrants_incoherents 2, non_uniforme 9, core_ratio_max 2, partagee 6, quadrants_insuffisants 1} (2 mixtes) | 0 % {non_uniforme 4, sans_bloc 16, partagee 4, quadrants_insuffisants 10} |
| 100 | 50 % {non_uniforme 2, bulle 2} | 75 % {sans_bloc 2, non_uniforme 2, bulle 2} |
| 120 | 67 % {bulle 2, non_uniforme 1} | 33 % {bulle 2, non_uniforme 2, sans_bloc 3} |

Bulles (fast-fill ok / échec / absent, mode lot) : 012 → 3/2/0, 020 → 12/1/0, 045 → 3/2/0,
060 → 3/0/0, 080 → 3/0/0, 100 → 4/2/0, 120 → 4/2/0.

Écart de masque manuel approximé (`--manual-mask approx`) vs vrai chemin Qt (`--manual-mask qt`) :
37 % avant correction du sens de bouchage des contreformes → 5,6 % après (`fill_poly`, M7).
Le mode `qt` rejoue le vrai chemin DrawingManager/ImageViewer : écart nul par construction, sert
de référence.

**Critère de couverture ajouté (consigne critic pass 2, #6)** : part de blocs `text_free` traités
en uni + ventilation des raisons de skip, mesurées ci-dessus. **Le seuil de suffisance reste à
fixer par Philippe**, après la revue visuelle — les chiffres seuls ne distinguent pas un skip
légitime (bulle proche, tracé protégé) d'un skip qui prive une légende exploitable de N1.

**Observation** : en mode manuel, un grand nombre de skips `sans_bloc` apparaît (composantes
fragmentées ne touchant la graine d'aucun bloc — voir §11, piste de suivi).

**9.3 — Tests verts, invariant prouvé** : 139 tests passés, `test_cleaning_invariant.py` prouve
que les deux cases décochées reproduisent `generate_mask` et le nettoyage des bulles octet pour
octet.

## 10. Point de test manuel

`uv run comic.py` → Réglages > Outils > Image Cleaning : cocher « Automatic flat fill » et
« Protect thin straight lines (panel borders) », marge 3 → page de référence → **Detect → Segment
→ Clean**.

Attendu : légendes en fond papier uni sans tache, bords de case continus, bulles au moins aussi
propres qu'avant. Console : une ligne par page (`cleaning: page composantes=... uni=... lama=...
skip=... blocs_mixtes=...`), plus une ligne par bulle (`pipeline.inpainting`, format d'origine).

**Contre-épreuve** : recharger la page pour défaire le nettoyage précédent, **décocher les deux
cases**, marge 3, refaire Detect → Segment → Clean → le défaut d'origine doit être reproduit à
l'identique. Sinon, les réglages ne sont pas branchés. La config est relue à chaque nettoyage
(pas de valeur mise en cache entre deux passages).

## 11. Défauts connus hors périmètre

- **LaMa invente des aplats blancs** sur des légendes posées sur du dessin (limite du modèle,
  préexistante, hors périmètre — voir §2, le modèle n'est pas remplacé dans ce lot).
- **Résidus fantômes de texte** après nettoyage (préexistant).
- **Patchs webtoon découpés sans marge** (`pipeline/webtoon_batch/chunk.py`) : défaut amont,
  non corrigé dans ce lot (candidat PR amont, voir `specs/00-feuille-de-route.md` §5).
- **Lecture de widgets Qt depuis le thread worker** (`cleaning_config_from_settings_page` appelée
  depuis le worker, motif déjà existant dans `get_config`, `batch_processor.py`) : défaut amont,
  non traité (voir `CLAUDE.md`).
- L'échantillon de test (« Fun Home », 7 pages) ne contient pas le cas exact du rapport initial
  (légende collée à un bord sur fond **non blanc**) : la calibration §4 repose sur les cas
  disponibles dans le banc, pas sur ce cas précis.
- **(Jalon 2)** Corpus limité à un seul album au trait (« Fun Home ») ; pages hachurées non
  testées — seul le plafond `line_max_protected_share` (0,35) borne le comportement dans ce cas,
  non mesuré.
- **(Jalon 2)** En mode manuel, le masque de bulle dépasse la zone d'exclusion
  `bubble_ring_exclusion` (7 px) dès `free_dilate_iterations ≥ 4` (redilatation 5×5 ×
  itérations) — documenté, non corrigé (consigne critic pass 2 #12).
- **(Jalon 2)** `connected_components_with_stats` (N1) alloue `np.indices` int64 pleine page
  (~153 Mo sur un chunk webtoon) pour des centroïdes inutilisés — documenté, non corrigé
  (consigne critic pass 2 #13).
- **(Jalon 2)** Skips `sans_bloc` (composantes fragmentées ne touchant la graine d'aucun bloc en
  mode manuel, 11 sur la page 012) : non résolus, mécanismes candidats (fusion, proximité)
  retirés après mesure — voir §13.
- **(2026-09-15)** Fausses bulles corrigées à l'étage de la détection, pas dans ce module (ADR-011,
  `specs/decisions.md`) : certaines légendes narratives étaient classées `text_bubble` à tort par
  `create_text_blocks` (`modules/detection/base.py`), ce qui leur faisait suivre le chemin bulle
  (ellipse inscrite tronquant les coins) au lieu du chemin légende de ce module. Le banc doit être
  **relancé sur les 9 pages** avec les blocs regénérés après ce correctif avant toute nouvelle
  calibration — les chiffres de couverture ci-dessus (§9.2, §12) datent d'avant.

## 12. Jalon 2 — calibration sur la page de référence (2026-09-13)

> **Note (2026-09-15)** : les mesures et résultats de cette section (avant/après jalon 2) ont été
> produits avant le hotfix de détection ADR-011 (fausses bulles sur légendes narratives,
> `specs/decisions.md`). Banc relancé le 2026-09-15 sur les 9 pages avec les blocs regénérés par
> le détecteur corrigé — voir §12 bis ci-dessous pour les chiffres à jour.

**Diagnostic** (capture réelle de Philippe, 2026-09-13, mode manuel Detect → Segment → Clean,
page `funhome_012`) : traînées grises sous les 3 légendes narratives, bord supérieur des cases
rongé, bulles propres. Sur le banc : légendes 5 et 6 écartées `bulle_proche` (bulles collées au
bord supérieur des cases : bulle 0 à y=485, bulle 1 à y=492 ; masque manuel des légendes jusqu'à
≈494-500 ; chevauchement mesuré avec la zone bulle+7 : 15,6 % et 7,4 %) et la légende 6 aussi
`partagee` (la graine de la bulle 0, bbox ± 5 % + 5 px, remonte dans son masque) ; légende 8
`non_uniforme` (part 0,82 : cadre dessiné à la main, ondulé, non détecté par `run_ge` L=61) ; 11
composantes `sans_bloc` en mode manuel.

**Prototypes mesurés avant conception** : détection « encre fine (dark & ¬OPEN 15×15) ∧ étendue
≥ 61 ∧ ≥ 10 % hors masque » sur la page entière → 36 composantes gardées (les 5 cadres + traits
reliés), 2 mots liés correctement exclus, 32 ms ; mais 229 501 px protégés (20 % de la page) →
restriction aux bandes text_free : 17,5 % des bandes (plafond 35 %). Avec `core_ratio` calculé sur
l'anneau géométrique avant purge : légendes 5/6 → part 0,92, cohérence 1, `core_ratio` 0,80 (au
lieu de 0,89/0,92) → uni. Légende 8 : anneau avec 1 235 px teintés bleu pâle (RVB ≈ 195/222/246) =
fond à deux tons ; l'anneau-barrière (composante de fond adjacente) n'a eu aucun effet mesuré
(`n_ring` 6 048 → 5 777) → retiré.

**Décisions retenues** (ADR-010, `specs/decisions.md`) :

1. Chevauchement partiel avec la zone de bulle toléré jusqu'à `bubble_overlap_max = 0.20`
   (fraction de la composante) ; résolution des co-propriétaires : un seul text_free + des bulles
   sous le seuil → le text_free est propriétaire.
2. N2 v2 (`line_detector="components"`, défaut) : détection des traits fins par composantes
   connexes (pas nécessairement droites), par crop de bande (bbox ± (69+61)), seuil Otsu calculé
   sur les pixels des bandes, garde-fou « union des bbox texte brutes soustraite de la
   protection » (coût assumé : une légende posée SUR un bord de case perd la protection de ce
   bord sur sa largeur — défaut §1 ligne 3 recréé, figé par test), plafond de saturation
   `line_max_protected_share = 0.35` (au-delà, protection abandonnée sur la bande + warning,
   jamais de repli vers `runs`, qui protège davantage) ; `run_ge` conservé derrière
   `line_detector="runs"` (non exposé UI). Retrait du masque restreint à bandes ∩ ¬zone bulle
   (les bulles ne sont jamais amputées).
3. Contour de bulle exclu **par construction** du remplissage : clip réel
   (`build_bubble_clip_mask`, fonction libre de `modules/utils/image_utils.py`) dilaté de
   `bubble_interior_dilation = 4` px, calculé une fois par bulle après le fast-fill ; garde
   couleur (fast-fill vs médiane de l'anneau ≤ tolérance) sinon repli sur la zone rectangulaire ;
   repli explicite si clip absent (colonne CSV `clip_bulle`). Seuls les pixels réellement peints
   sont démasqués (`core \ core_fill` reste pour LaMa). Fondu bloqué sur le contour et
   l'intérieur.
4. `mask_entry` figé à l'entrée de N1 : décisions indépendantes de l'ordre des labels.
5. `core_ratio` calculé sur l'anneau géométrique avant purge (seuil 0,90 inchangé).
6. Mécanismes **retirés après mesure** : anneau-barrière (sans effet), fusion des fragments par
   bloc (le gros de chaque légende reste une composante ; miettes ≤ 404 px → LaMa), attribution
   par proximité (effet inconnu) — `sans_bloc` reste skippé, à réévaluer sur mesure (colonnes CSV
   `aire_core`, `bbox_core`, `distance_bloc_le_plus_proche` ajoutées pour ça).

**Résultats banc** (mêmes blocs figés, avant → après jalon 2) :

| Page | Lot : %uni avant → après | Manuel : %uni avant → après |
|---|---|---|
| 012 | 40 % → 100 % | 40 % → 100 % |
| 020 | 0 % → 0 % | — |
| 045 | 80 % → 80 % (mixtes 1 → 2) | 20 % → 20 % |
| 060 | 0 % → 0 % | — |
| 080 | 40 % → 30 % (mixtes 2 → 1) | 0 % → 10 % |
| 100 | 50 % → 50 % | 75 % → 75 % |
| 120 | 67 % → 67 % | 33 % → 67 % |

Temps ≈ inchangés (3,6–4,3 s/page CPU, LaMa dominant).

Page 012 par légende en mode manuel : 5 → uni (0,97), 6 → uni (0,98), 7 → uni, 8 → uni (0,93 ; la
conception prédisait un repli LaMa, l'aplat est visuellement propre sur la planche — à trancher
par Philippe en revue), 9 → uni.

Sweep (`bubble_overlap_max` 0,10 / 0,20 / 1,0) : 44,1 / 45,7 / 44,4 % uni global (6 pages, 030
écartée), mixtes 3 partout. `line_detector` : `components` 45,7 % vs `runs` 40,0 %.

**Tests** : 162 passés + 1 xfail à la rédaction (163 attendus après correctif d'une ligne en
parallèle). `test_cleaning_e2e_legende.py` (nouveau) : cadre ondulé + légende + bulle collée +
lavis. Ajoutés : (iv) co-propriété, (v) contour/intérieur de bulle intacts en égalité stricte,
(vi) `core \ core_fill` masqué, (vii) plafond de saturation, M2 figé, M3 réécrit, miettes, ordre
des labels, `out_mask ≤ mask`, marge 6, clip calculé une fois.

Bug amont trouvé en cours de route : `imkit/transforms.py:425-426` surestime largeur/hauteur des
composantes de 1 px (bornes de mahotas déjà exclusives) ; compensé dans
`modules/cleaning/uniform.py`, `imkit` non modifié (candidat PR amont, spec 00 §5).

**Point de test manuel de Philippe** (page 012) : cases cochées, marge 3, masque généré sans
retouche au pinceau (une retouche au pinceau blanc envoie la composante en `skip pinceau` et
retire la protection du cadre là où elle passe). Attendu : 3 légendes en papier uni d'un seul
tenant, bords continus, 5 bulles intactes contour compris, plus de bande grise au-dessus des
bulles du milieu. Contre-épreuve cases décochées → défaut d'origine reproduit. **En attente de son
retour.**

**Limites documentées, non corrigées** : voir §11.

## 12 bis. Banc relancé après le hotfix de détection (2026-09-15, ADR-011)

Banc relancé sur les 9 pages avec les blocs regénérés par le détecteur corrigé
(`bench/out/blocks_v3`, sorties `v3_lot` et `v3_manuel`).

**%uni par page, mode lot / mode manuel `qt` (skips principaux) :**

| Page | Lot : %uni {skips} | Manuel qt : %uni {skips} |
|---|---|---|
| 011 | 17 % {non_uniforme 5, partagee 2, ring_trop_petit 2, bulle 3} | 17 % {sans_bloc 9, partagee 2} |
| 012 | 100 % {} | 100 % {sans_bloc 17} |
| 020 | 33 % (avant correctif : 0 %) | 33 % |
| 045 | 80 % | 20 % |
| 060 | 0 % (page sans légende) | 0 % |
| 080 | 30 % | 10 % |
| 100 | 57 % (avant : 50 %) | 57 % (avant : 75 %) |
| 120 | 75 % (avant : 67 %) | 75 % (avant : 67 %) |

Page 011 : la légende du bas, reclassée `text_free` par le correctif ADR-011 (elle était
`text_bubble` à tort), suit désormais le chemin légende ; sur cette page son nettoyage passe par
LaMa sur fond blanc, sans coin coupé (contrairement au défaut d'origine — voir JOURNAL
2026-09-15). Page 020 : un bloc reclassé légende passe en aplat (0 % → 33 %).

**Temps** : +0,3 à +2 s par page vs avant nettoyage (4 à 6 s/page CPU, LaMa dominant) — **ce n'est
plus « non supérieur »** comme mesuré au jalon 1 (§9.2) : la détection par composantes et le calcul
des clips de bulle coûtent ~0,5-1 s par page supplémentaire. Bulles (fast-fill ok/échec par page) :
inchangées par rapport au jalon 2.

**Observation** : en mode manuel, les skips `sans_bloc` restent élevés (9 à 26 fragments par
page), tous envoyés à LaMa, sans défaut visuel rapporté — piste toujours ouverte (§11, spec 00
§5).

## 13. Ce qui n'est pas fait

- Remplacement ou ajout de modèle d'inpainting.
- Détection des cases (N3), sauf verdict contraire du banc.
- Modification du rendu du texte.
- Choix final du jeu de paramètres §4 (revue visuelle de Philippe).
- Seconde dilatation manuelle (`generate_mask_from_strokes`) non réglée par un paramètre séparé
  du lot dans ce lot (voir §6, note).
