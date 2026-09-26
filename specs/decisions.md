# Décisions d'architecture (ADR)

## ADR-001 — Base du fork : `filvyb/comic-translate`

Date : 2026-09-12
Statut : Adoptée

**Contexte** : `ogkalu2/comic-translate` (officiel) impose un compte
(`is_logged_in()` depuis le commit `3bb8fd3`, 2026-01-28, v2.6.0) même pour un
traducteur Custom local. `filvyb/comic-translate` (`059046d`, 2026-07-10) suit
l'officiel sans ce code d'authentification. Voir spec 00 §1.

**Décision** : fork basé sur `filvyb` (`059046d`). `ogkalu2` gardé en remote
`upstream` pour récupérer des correctifs au cas par cas, pas de merge global.
Licence Apache-2.0 conservée des deux côtés (`LICENSE`, mentions d'origine).

**Conséquences** : pas de blocage par compte, mais pas de suivi automatique des
correctifs upstream — veille manuelle nécessaire.

## ADR-002 — `requirements.txt` source unique des dépendances

Date : 2026-09-12
Statut : Adoptée

**Contexte** : le dépôt a `requirements.txt` (utilisé par `filvyb`/`upstream`)
et `pyproject.toml`/`uv.lock` (créés par `uv init`/`uv add`) après l'installation
initiale. Il faut une source de vérité qui ne complique pas les rebase.

**Décision** : `requirements.txt` reste la seule source éditée à la main.
`pyproject.toml` est généré : bloc `[project].dependencies` entre marqueurs
`# --- sync_deps: begin/end ---`, régénéré par `tools/sync_deps.py --write`
(échoue bruyamment si les marqueurs sont absents/dupliqués, jamais de
réécriture silencieuse). `--check` (défaut) sert de garde-fou en CI/local.
`uv.lock` et `.python-version` sont versionnés.

Alternative rejetée : `pyproject.toml` avec `dynamic = ["dependencies"]`
pointant vers `requirements.txt` — écarté car moins explicite pour `uv` et ne
supprime pas le besoin de vérifier la cohérence.

**Conséquences assumées** : diffs volumineux sur `pyproject.toml`/`uv.lock` et
conflits possibles sur `.gitignore` lors des rebase sur `filvyb`/`upstream`
(qui ne connaissent pas ces fichiers) — jugé préférable à une double source de
vérité qui diverge silencieusement.

## ADR-003 — Pas de relais HTTP entre l'app et Ollama

Date : 2026-09-12
Statut : Adoptée

**Contexte** : spec 00 §3, décision Philippe : « une couche supplémentaire
pour rien ».

**Décision** : toute adaptation de requête (réflexion, `max_tokens`, timeout)
se fait dans l'app (`modules/translation/llm/compat.py`, surcharge de
`CustomTranslation._make_api_request`), pas via un proxy intermédiaire.

**Conséquences** : le fork dépend du format `/v1` d'Ollama tel qu'observé en
v0.34.0 ; un changement de comportement d'Ollama impose de revoir `compat.py`
directement, sans couche d'abstraction supplémentaire à maintenir en échange.

## ADR-004 — Défauts du traducteur Custom pour Ollama

Date : 2026-09-12
Statut : Adoptée

**Contexte, mesuré sur Ollama 0.34.0 (Mini)** :
- `translategemma:12b` (famille gemma3, capacités `completion, vision`, pas de
  `thinking`) + `reasoning_effort: none` + `max_tokens` → 200, JSON valide,
  ~10 s. Pas de dégradation malgré l'absence de capacité `thinking`.
- `gemma4:12b-mlx` (capacités `completion, vision, audio, tools, thinking`)
  sans réglage → réflexion active, budget de tokens consommé dans le champ
  `reasoning`, `content` vide, `finish_reason: length` (panne d'origine
  reproduite). Avec `reasoning_effort: none` → JSON complet en 6,5 s.
- `max_completion_tokens: 5` → ignoré par Ollama (191 tokens générés,
  `finish_reason: stop`). `max_tokens: 5` → honoré (`finish_reason: length`).

**Décision** : trois réglages Custom persistés indépendamment de « Save Keys »
(groupe QSettings `custom_llm`) : réflexion désactivée (coché par défaut),
renommage `max_completion_tokens` → `max_tokens` (coché par défaut), timeout
180 s (bornes 10–1800, défaut si valeur aberrante). Comportement GPT/OpenAI
inchangé (`gpt.py` garde `max_completion_tokens`, pas de `reasoning_effort`,
timeout 80 s codé en dur).

**Conséquences** : le banc utilise la même borne de timeout (10–1800) que
l'UI ; une valeur `--timeout` hors plage retombe silencieusement sur 180 s.

## ADR-005 — Fuite d'identifiants QSettings constatée et reportée

Date : 2026-09-12
Statut : Constatée, non corrigée (hors périmètre spec 01)

**Contexte** : dans `app/ui/settings/settings_page.py`, `get_all_settings()`
inclut `credentials` (groupe QSettings), et `process_group` écrit
`credentials/<Service>/api_key` en clair sans condition sur « Save Keys ».
`settings.remove('credentials')` est appelé alors que le code est déjà dans
`beginGroup('credentials')` : la suppression vise donc `credentials/credentials`
(no-op). Résultat : décocher « Save Keys » n'efface aucune clé déjà écrite.

**Décision** : mécanisme préexistant à `059046d`, non introduit par le fork
(le groupe `custom_llm` ajouté par F2 est séparé et ne contient aucun secret).
Reporté plutôt que corrigé dans ce lot — hors du périmètre spec 01 (socle) et
non demandé par la conception validée.

**Conséquences** : à corriger dans un lot ultérieur ou à proposer en amont
(candidat PR, spec 00 §5). Ne pas confondre avec les réglages `custom_llm` du
fork, qui ne sont pas concernés.

## ADR-006 — Périmètre et stratégie du contexte SSL (F1)

Date : 2026-09-12
Statut : Adoptée, priorité basse

**Contexte** : panne `SSL: CERTIFICATE_VERIFY_FAILED` constatée le 2026-09-11
sur l'app **empaquetée** (DMG) au téléchargement du modèle RT-DETR. Depuis les
sources (`uv run comic.py`, Python 3.12.11 géré par `uv`, OpenSSL 3.0.16) :
`urlopen('https://huggingface.co/...')` sans contexte renvoie 200,
`ssl.get_default_verify_paths().openssl_cafile` (`/private/etc/ssl/cert.pem`)
existe. **La panne ne se reproduit pas depuis les sources et sa cause sur le
DMG n'a pas été diagnostiquée.**

**Décision** : implémenter tout de même `modules/utils/ssl_context.py` —
repli sur `certifi` uniquement si aucun magasin système n'est détecté et
qu'aucune variable `SSL_CERT_FILE`/`SSL_CERT_DIR` n'est définie, jamais de
désactivation de la vérification. Branché dans `download_file.py`
(2 lignes `# fork:`). Priorité basse (robustesse et contribution amont
possible, pas un correctif vérifié de la panne DMG).

**Interdiction explicite** : ne jamais écrire, dans la spec 01 ou ailleurs,
que F1 corrige la panne du DMG, ni que le critère de réussite spec 01 §6.1
valide F1 — ce critère porte sur le lancement depuis les sources, où la panne
ne s'est pas reproduite avant même l'implémentation de F1.

**Hors périmètre** : chemins de téléchargement `pororo` (`urlretrieve` dans
`pororo/models/brainOCR/utils.py:705`, chemin mort ; `wget` dans
`pororo/tasks/utils/download_utils.py:292`, OCR coréen) — non couverts par F1.

## ADR-007 — Nettoyage des légendes : option A, point de convergence `inpaint_image`, composantes connexes

Date : 2026-09-13
Statut : Adoptée

**Contexte** : spec 02, deux flux distincts (lot et manuel) produisent un masque avant
l'inpainting LaMa, avec des points d'entrée différents (`generate_mask` vs
`generate_mask_from_strokes`) mais un seul point de convergence commun :
`InpaintingHandler.inpaint_image` (`pipeline/inpainting.py`).

**Options considérées** :
- **A (retenue)** : paquet pur `modules/cleaning/` (numpy/mahotas/imkit, zéro Qt, zéro import
  de `pipeline/`), fonction `clean_page(image, mask, blk_list, cfg, *, protect_mask=None,
  bubble_cleanup=None)` appelée en un point unique dans `inpaint_image`, avant
  `_apply_fast_bubble_cleanup`. `bubble_cleanup` est **injecté** par l'appelant (jamais importé
  par `modules/cleaning`), ce qui garantit qu'un test peut vérifier le contrat sans dépendre de
  `pipeline/inpainting.py`.
- **B (rejetée)** : tout le traitement dans `build_block_mask_data` (côté construction du masque
  par bloc). Rejetée : la re-dilatation déjà présente à cet endroit défait tout travail de
  protection des traits (N2) fait en amont, et 4 appelants différents auraient dû être modifiés
  de façon cohérente.
- **C (rejetée)** : généraliser `_apply_fast_bubble_cleanup` (déjà présent pour les bulles) aux
  blocs `text_free`. Rejetée : ce code est dans un fichier Qt-adjacent du fork amont, avec des
  critères déjà entrelacés (bulles, résidus, élagage) ; y ajouter ~150 lignes de logique
  supplémentaire l'aurait rendu difficile à faire évoluer et à rebaser sur `upstream`.

**Décision** : option A. Architecture par **composantes connexes attribuées par graine**
(voir spec 02 §3) plutôt qu'un simple anneau bbox : une composante est éligible au remplissage
uni seulement si sa graine ne revendique qu'un seul bloc `text_free`, à distance suffisante des
bulles et hors des tracés manuels protégés — sinon elle est laissée intacte (`skip`), jamais
traitée à moitié.

**Conséquences** : `modules/cleaning/` reste testable en isolation (aucun import Qt/pipeline).
Le contrat de non-écriture (identité d'objet en config inerte, verbatim du `bubble_cleanup`
injecté) est la garantie centrale qui permet de prouver par test que les deux cases décochées
reproduisent l'app d'origine.

## ADR-008 — Protection des fichiers amont contre le formatage automatique

Date : 2026-09-13
Statut : Adoptée

**Contexte** : un hook global `PostToolUse` sur `Edit|Write` exécute `ruff format` après chaque
modification de fichier. Pendant l'implémentation de la spec 02, ce hook a reformaté **9 fichiers
d'origine** (amont, hors `modules/cleaning/`) en intégralité : 1 594 lignes touchées au lieu des
748 lignes réellement modifiées par le fork. Cela aurait rendu les futurs rebase sur `filvyb`/
`upstream` beaucoup plus difficiles (diffs illisibles, conflits sur des lignes jamais touchées
par le fork).

**Réparation** : restauration des fichiers à leur état d'origine (`git checkout` / recopie),
puis réapplication manuelle des seuls hunks marqués `# fork:`. Résultat : 243 lignes touchées
sur 33 lignes réellement nécessaires (l'écart restant vient de contexte de diff, pas de
reformatage).

**Décision** : `[tool.ruff]` dans `pyproject.toml` porte `force-exclude = true` (s'applique même
aux chemins passés explicitement par le hook Edit/Write) et une liste explicite de dossiers
d'origine exclus (`app/`, `modules/detection/`, `modules/inpainting/`, `modules/ocr/`,
`modules/rendering/`, `modules/translation/`, `modules/utils/`, `modules/__init__.py`,
`pipeline/`, `imkit/`, `controller.py`, `comic.py`, `tests/test_app.py`). Ruff ne traite pas la
négation (`!motif`) dans `extend-exclude` comme le ferait `.gitignore` pour un sous-dossier d'un
chemin déjà exclu (vérifié : `!modules/cleaning/` reste sans effet) — les sous-dossiers d'origine
de `modules/` sont donc énumérés explicitement plutôt que d'exclure `modules/` en bloc.
`modules/cleaning/` et `tools/` restent lintés et formatés : ce sont des fichiers du fork, pas
d'origine.

**Conséquences** : ne jamais retirer `force-exclude` ni la liste `extend-exclude` sans revérifier
qu'un nouveau dossier d'origine touché par le fork y figure. Tout nouveau fichier amont modifié
(`# fork:`) doit être ajouté à cette liste avant la première édition, pas après.

## ADR-009 — Locale numérique forcée à `C` après `QApplication`

Date : 2026-09-13
Statut : Adoptée

**Contexte** : « Reconnaître » (OCR) rendait tous les blocs vides sans erreur visible, journal
`OCR completed and cached for N blocks` malgré des textes vides. Diagnostic : `QApplication`
applique la locale système (`LC_NUMERIC=fr_FR.UTF-8`, virgule décimale) ; `onnxruntime` 1.30 (CPU,
macOS arm64), importé plus tard par imports paresseux des moteurs, mésinterprète alors des
flottants du runtime et renvoie une sortie constante (argmax = blanc) pour le modèle de
reconnaissance PP-OCR `en_PP-OCRv5_rec_mobile_infer.onnx`, indépendamment de l'image en entrée.
Reproduit hors app par `locale.setlocale(LC_ALL, "fr_FR.UTF-8")` avant `import onnxruntime` ; non
reproduit en locale `C`, ni si onnxruntime est importé avant Qt. LaMa (inpainting) et le
détecteur RT-DETR ne sont pas affectés (sorties identiques au bit près sous les deux locales).

**Décision** : `locale.setlocale(locale.LC_NUMERIC, "C")` juste après la création de
`QApplication` dans `comic.py` (2 lignes `# fork:`). Vérifié hors écran : 10/10 blocs lus sur une
page, champ source rempli.

**Alternatives rejetées** :
- Importer `onnxruntime` avant Qt : fragile, dépend de l'ordre des imports paresseux des moteurs
  (détection, OCR, inpainting importés à des moments différents selon le flux) — un futur import
  réordonné referait échouer l'OCR silencieusement.
- `LC_ALL=C` dans un lanceur externe (script shell, `.plist`) : ne couvre pas `uv run comic.py`
  lancé directement, le cas d'usage principal en développement.

**Conséquences** : aucune sur l'affichage — seul `LC_NUMERIC` est touché, pas `LC_ALL` ; Qt garde
sa propre `QLocale` pour l'interface (formats de date, nombres affichés). Candidat PR amont
(invisible pour des développeurs en locale anglaise, spec 00 §5). Règle ajoutée à `CLAUDE.md` :
tout script créant une `QApplication` avant d'importer `onnxruntime` doit remettre `LC_NUMERIC` à
`C` juste après.

## ADR-010 — Jalon 2 nettoyage : contour réel des bulles, traits fins par composantes, mécanismes retirés après mesure

Date : 2026-09-13
Statut : Adoptée

**Contexte** : calibration sur la capture réelle de Philippe (`funhome_012`, mode manuel) :
traînées grises sous 3 légendes narratives, bord supérieur des cases rongé. Diagnostic sur le
banc : légendes collées à un bord de bulle écartées `bulle_proche`/`partagee` (chevauchement
bulle+7 mesuré 15,6 % et 7,4 %) ; une légende à cadre à la main ondulé non détectée par `run_ge`
(L=61, part 0,82, `non_uniforme`) ; 11 composantes `sans_bloc` en manuel.

**Décision** :

1. **Chevauchement bulle toléré** jusqu'à `bubble_overlap_max = 0.20` (fraction de la
   composante) ; résolution multi-propriétaires : un seul text_free + des text_bubble sous le
   seuil → le text_free est propriétaire unique (au-delà → `bulle_proche` ; deux text_free →
   `partagee`).
2. **N2 v2** (`line_detector="components"`, défaut) : traits fins détectés par composantes
   connexes (pas nécessairement droites) sur un crop de bande (bbox ± (line_band_margin +
   line_length)), seuil Otsu local aux bandes, garde-fou « bbox texte brute soustraite de la
   protection », plafond `line_max_protected_share = 0.35` (au-delà : protection abandonnée sur
   la bande + `logger.warning`, jamais de repli vers `runs`). `run_ge` conservé derrière
   `line_detector="runs"`, non exposé UI, gardé comme mesure comparée et filet de secours
   explicite.
3. **Contour de bulle exclu par construction** : `build_bubble_clip_mask` (fonction libre,
   `modules/utils/image_utils.py`) dilaté de `bubble_interior_dilation = 4` px, calculé une fois
   par bulle après le fast-fill (jamais recalculé par composante) ; garde couleur (fast-fill vs
   médiane de l'anneau ≤ tolérance), sinon repli sur la zone rectangulaire ; repli explicite si le
   clip est absent/vide (colonne CSV `clip_bulle`). Seuls les pixels réellement peints sont
   démasqués (`mask_crop[core_fill] = 0`) ; `core \ core_fill` reste masqué pour LaMa — jamais de
   pixel démasqué non peint.
4. `mask_entry` figé à l'entrée de N1 (copie de `residual_mask > 0`) : les décisions ne dépendent
   plus de l'ordre d'attribution des labels.
5. `core_ratio` calculé sur l'anneau **géométrique avant purge** (dilaté/érodé, avant retrait du
   masque, du halo protégé et des bulles), seuil 0,90 inchangé.

**Alternatives rejetées, avec la mesure qui les a rejetées** :
- **Anneau-barrière** (composante de fond adjacente au trait, pour isoler un fond à deux tons) :
  sur la légende à cadre ondulé (fond bicolore, 1 235 px teintés bleu pâle RVB ≈ 195/222/246),
  aucun effet mesuré (`n_ring` 6 048 → 5 777) → retiré.
- **Fusion des fragments par bloc** (`core` = union de toutes les composantes attribuées au même
  bloc) : le gros de chaque légende reste déjà une composante unique en pratique ; les miettes
  restantes (≤ 404 px) tombent sous `ring_min_pixels` → LaMa de toute façon. Retenir la fusion
  aurait exigé une règle « miettes » jugée risquée (texte non inpainté possible si mal groupé) →
  retiré, `sans_bloc` reste skippé.
- **Attribution par proximité** (`seed_fallback_distance`, rattacher une composante orpheline au
  bloc le plus proche) : effet nul ou inconnu sur le corpus disponible → retiré. Colonnes CSV
  `aire_core`, `bbox_core`, `distance_bloc_le_plus_proche` ajoutées pour réévaluer sur mesure si
  le besoin réapparaît.
- **`core_ratio` sur l'anneau après purge** (option initiale) : sur les légendes collées à une
  bulle, l'amputation de l'anneau côté bulle fait grimper `core_ratio` artificiellement (0,89-0,92
  au lieu de 0,80 mesuré sur l'anneau géométrique) → écarté au profit de la mesure avant purge.

**Conséquences assumées** :
- Une légende posée **sur** un bord de case perd la protection de ce bord sur sa largeur (garde-
  fou bbox texte, point 2) — recrée partiellement le défaut d'origine (spec 02 §1, ligne 3) dans
  ce cas précis ; figé par test plutôt que corrigé, car l'alternative (ne pas soustraire la bbox
  texte) laissait passer des hachures chaînées au cadre comme texte fantôme jamais inpainté.
- Masque de bulle en mode manuel : l'hypothèse « bbox ± `bubble_ring_exclusion` (7 px) contient
  le masque bulle » n'est vraie qu'à `free_dilate_iterations ≤ 3` ; au-delà (redilatation 5×5 ×
  itérations), le résidu de masque bulle peut déborder de cette zone — documenté, non corrigé.
- `connected_components_with_stats` (N1) alloue `np.indices` int64 pleine page (~153 Mo sur un
  chunk webtoon) pour des centroïdes inutilisés — documenté, non corrigé (candidat optimisation
  future si le webtoon devient un cas réel de nettoyage).
- Bug amont trouvé en cours de mesure : `imkit/transforms.py:425-426` surestime largeur/hauteur
  des composantes de 1 px (bornes de mahotas déjà exclusives) ; compensé côté
  `modules/cleaning/uniform.py`, `imkit` lui-même non modifié (candidat PR amont, spec 00 §5).
- `sans_bloc` (composantes fragmentées ne touchant la graine d'aucun bloc en mode manuel, 11 sur
  la page de référence) reste non résolu : les deux mécanismes candidats (fusion, proximité) ont
  été mesurés et retirés faute d'effet démontré — à reprendre seulement si une nouvelle mesure le
  justifie.

## ADR-011 — Marge minimale bulle/texte de 3 px avant appariement en détection

Date : 2026-09-15
Statut : Adoptée

**Contexte** : capture de Philippe (2026-09-15, page 11 de l'album de test) — masque de
segmentation d'une légende narrative de 3 lignes en forme d'ellipse tronquant le début de la
première ligne et la fin de la dernière ; les autres légendes et les bulles étaient correctes.
Diagnostic : RT-DETR émet une boîte « bulle » calée exactement sur la légende (bulle
`[31,609,797,682]`, texte `[30,610,797,681]`) ; `create_text_blocks`
(`modules/detection/base.py`) classe alors le bloc `text_bubble` ; `clip_mask_components_to_bubble`
ne trouve pas de contour de bulle fermé (il n'y en a pas, RT-DETR a détecté le cadre de la
légende) et retombe sur l'ellipse inscrite (`build_bubble_clip_mask`), qui tronque les coins du
rectangle de texte.

**Mesure** (242 pages de l'album, 1 388 blocs classés bulle) : marge minimale entre boîte de
bulle et boîte de texte (`min(tx1-bx1, ty1-by1, bx2-tx2, by2-ty2)`). Les fausses bulles ont une
marge de 0 à 1 px (374/390 blocs sous 2 px — 28 % de tous les blocs « bulle » de l'album). Les
vraies bulles ont une marge ≥ 4 px et un rapport d'aire boîte-bulle/boîte-texte ≥ 1,18 (médiane
1,69, marge médiane 10 px). Distribution bimodale nette : aucun bloc entre 2 et 4 px, hors 16 cas
à rapport d'aire 1,33 (marge probablement autour de 2-3 px, non séparés davantage faute de
nécessité).

**Décision** : `MIN_BUBBLE_MARGIN_PX = 3` en constante de classe sur `DetectionEngine`
(`modules/detection/base.py`). Dans `create_text_blocks`, l'appariement bulle/texte est rejeté
si la marge minimale est sous ce seuil, y compris en cas de chevauchement partiel (marge négative
sur un seul côté, IoU ≥ 0,2) — le bloc redevient `text_free` s'il n'existe pas d'autre bulle
candidate. 16 lignes `# fork:`, seul point d'appariement du dépôt (le flux webtoon et le flux lot
appellent tous deux `create_text_blocks`, aucun code dupliqué à corriger ailleurs).

**Alternatives rejetées** :
- **Corriger à l'étage du masque** (dans `build_bubble_clip_mask` ou
  `clip_mask_components_to_bubble`, ex. détecter l'absence de contour fermé et ne pas tronquer) :
  rejetée — le bloc reste classé `text_bubble` à tort, ce qui fausse aussi le fast-fill bulle
  (`_apply_fast_bubble_cleanup`) et empêche le bloc de bénéficier du chemin légende (spec 02,
  aplat + protection des cadres). Corriger la classification en amont règle les deux problèmes
  d'un coup.
- **Reclasser seulement côté `modules/cleaning`** (heuristique géométrique dans le module de
  nettoyage, sans toucher à la détection) : rejetée — `modules/cleaning` est un paquet pur sans
  connaissance du contexte RT-DETR/`TextBlock.bubble_bbox`, et la mauvaise classification
  `text_bubble` contamine aussi l'OCR/le rendu en aval de la détection, pas seulement le
  nettoyage. Corriger à la source (détection) est plus simple et couvre tous les usages en aval.

**Conséquences assumées** :
- Un chevauchement partiel bulle/texte à marge < 3 px est toujours rejeté, y compris dans le cas
  théorique d'une vraie petite bulle très ajustée au texte — non rencontré dans les 242 pages
  mesurées, jugé acceptable (conservateur, aucune vraie bulle de l'album n'est concernée par le
  rejet mesuré).
- Vérifié sur le banc (9 pages) : blocs bulle 40 → 38 (`funhome_011` et `funhome_020` basculent un
  bloc chacune vers `text_free`). Le banc de nettoyage (spec 02) doit être relancé sur ces 9 pages
  avec les nouveaux blocs avant toute nouvelle calibration — les chiffres de couverture §9.2/§12
  de la spec 02 datent d'avant ce correctif.
- Candidat PR amont (spec 00 §5) : filtre générique, indépendant du fork Ollama.

## ADR-012 — Versions par bloc : attribut sur `TextBlock`, enregistrement à l'affectation, pré-état et flush

Date : 2026-09-16
Statut : Adoptée (jalon A de la spec 03, test manuel de Philippe en attente)

**Contexte** : `specs/03-inventaire.md` §1.3 constate que `TextBlock.translation` est un champ
scalaire unique, écrasé en place par 7 chemins (LLM, cache, mise en casse, édition manuelle,
Rechercher/Remplacer, lot), sans aucune version conservée (E3 de la spec 03, « absent »). Chaîne
de conception : architect → critic pass 1 (« Architect must revise », 5 bloquants B1-B5) →
conception v2 → critic pass 2 (« Acceptable to proceed », 5 majeurs traités en consignes) →
implementer → tester.

**Bloquants du critic pass 1, retenus dans la conception v2** :
- **B1** : un deuxième « Traduire » sur un bloc déjà traduit est souvent servi par le cache
  (`_can_serve_all_blocks_from_translation_cache`), qui ne rappelle jamais le traducteur et écrase
  `blk.translation` avec la valeur cachée — une édition manuelle entre-temps disparaît sans laisser
  de trace si l'écriture n'est pas interceptée à l'affectation.
- **B2** : l'édition du champ traduction réécrit `blk.translation` à chaque frappe
  (`update_text_block_from_edit`), jamais via une commande Qt — rien à intercepter côté undo/redo,
  seul le pré-état + flush peut la capter.
- **B3** : enregistrer seulement la valeur nouvelle perd toute écriture non instrumentée entre deux
  points de capture (correction manuelle perdue par une retraduction suivante) — d'où la règle
  « pré-état » : avant d'écraser un champ, pousser la valeur qu'il portait si elle divergeait de la
  tête du journal.
- **B4** : OCR et traduction en mode bloc unique travaillent sur des **copies jetables**
  (`deep_copy`) — instrumenter les processeurs journaliserait sur des objets détruits ; le vrai
  point de convergence est l'**affectation** sur le bloc vivant (6 sites : `ocr_handler.py:46/:80`,
  `translation_handler.py:56/:87`, `cache_manager.py:339/:346`).
- **B5** : `set_upper_case` s'applique après chaque traduction, pas seulement au rendu — la
  comparaison de tête doit être insensible à la casse (`casefold`), sinon le marqueur « entrée
  courante » n'est jamais vrai et une correction de casse pure crée une fausse entrée.

**Décision** — module pur `modules/history/versions.py` (aucun import PySide6, importable depuis
un worker et depuis les tests hors `--gui`) :
- `set_text(blk, field, value, origin, meta)` est le point d'entrée unique pour une écriture
  instrumentée. Ordre impératif (consigne Ma du critic pass 2) : valeur courante → tête du journal
  **du champ** → pré-état si la valeur courante divergeait de la tête (`manual` si le champ avait
  déjà une tête, `prior` sinon — décision par champ, pas par bloc, consigne Mc) → relecture de la
  tête → dédoublonnage par `casefold` contre la nouvelle tête → `setattr` **dans tous les cas**
  (consigne Mb, y compris dédoublonnage ou dépassement de plafond) → `append` si ni dédoublonné ni
  rejeté. Invariant après appel (sauf rejet `MAX_VALUE_CHARS`) :
  `versions_of(blk, field)[-1]["value"].casefold() == getattr(blk, field).casefold()`.
- `snapshot`/`record_diff` couvrent les processeurs OCR/traduction (`OCRProcessor.process`,
  `Translator.translate`) — seul endroit où le nom du moteur (`ocr_model`, `translator_key`) est
  disponible pour `meta` ; le diff porte sur le bloc vivant après que le moteur a déjà écrit le
  champ.
- `flush_pending(blk_list)` rattrape les écritures non instrumentées (frappe directe dans les
  champs source/traduction, B2) par le mécanisme du pré-état, et c'est le **seul** point qui élague
  le journal (`prune`) — restreint au fil GUI (une entrée ajoutée par un worker est sûre, une
  suppression concurrente ne l'est pas). Appelé depuis `save_image_state`
  (`app/controllers/image.py:1020-1029`), point de passage unique vérifié pour changement de page,
  sauvegarde manuelle/auto, exports et multi-pages.
- Journal en place, jamais de réaffectation : `blk.__dict__.setdefault("versions", [])`, `append`
  seulement — un `RectCommandBase` (`app/ui/commands/base.py:174-178`) peut faire pointer deux
  `TextBlock` vivants vers la même liste après une suppression annulée ; réaffecter casserait cet
  aliasing préexistant (déjà présent pour `texts`/`lines`).
- Restauration : `commands.py` (`RestoreVersionCommand`), zéro ligne amont. `redo` :
  `_commit_pending_text_command()` d'abord (une édition en attente à 400 ms ne doit pas écraser la
  restauration), puis `set_text(origin=restore)`, puis `apply_text_from_command` si le bloc a un
  item de texte rendu ; `blockSignals` sur `s_text_edit` **et** `t_text_edit` pour éviter qu'écrire
  dans un champ ne déclenche la réécriture de l'autre. `undo` : retire l'entrée `restore` seulement
  si elle est en tête (`pop_head_if_origin`), ne retire jamais le pré-état qu'elle a pu créer.
- Sérialisation : `versions` est un attribut `list[dict]` de types simples (str/dict), donc
  automatiquement sérialisé par `TextBlock.__dict__` (`app/projects/parsers.py:57-63/:174-178`) —
  aucun encodeur dédié nécessaire.
- Plafonds : 12 entrées par champ, 2 000 caractères par valeur (au-delà : champ écrit quand même,
  aucune entrée, un seul avertissement journalisé), 6 000 caractères par bloc toutes entrées
  confondues ; la plus ancienne entrée de chaque champ est épinglée (« texte d'origine »), FIFO
  sinon.

**Alternatives rejetées** :
- **Versions dans `image_state`, indexées par identité de bloc** : rejetée, aucun identifiant
  stable sur `TextBlock` (`xyxy` bouge à chaque déplacement/redimensionnement) — l'indexation
  romprait à la première édition de géométrie.
- **Propriétés `text`/`translation` sur `TextBlock`** (interception à la lecture/écriture) :
  rejetée — renommer le stockage sous-jacent casserait le chargement des projets de l'app
  d'origine (blocs vides à l'ouverture, `__dict__.update` de `parsers.py:174-178` court-circuite
  toute property) ; une casse ou une frappe intermédiaire polluerait aussi le journal sans le
  filtre du pré-état.
- **Diff aux seuls processeurs** (v1 du critic, sans les 6 sites d'affectation) : rejetée — ne voit
  ni le cache du deuxième « Traduire » (B1), ni les copies jetables du chemin bloc unique (B4), ni
  l'édition du champ avant tout rendu (B2) ; les 5 bloquants du critic pass 1 portent tous sur
  cette omission.
- **`app/history/`** comme emplacement du paquet : rejeté, `app/` est exclu de ruff en bloc
  (ADR-008, dossier amont) — `modules/history/` reste linté comme `modules/cleaning/` et `tools/`.

**Conséquences et défauts connus (à ne pas « corriger par surprise »)** :
- Le traitement par **lot** remplace `blk_list` entier pour la page
  (`pipeline/batch_processor.py:441-443`) sans passer par `set_text` : le journal des blocs
  remplacés est perdu. Pas de report positionnel par IoU au jalon A (idée en réserve,
  `specs/00-feuille-de-route.md` §5).
- Le **webtoon** n'appelle ni `flush_pending` ni, par construction, le pré-état sur ses propres
  écritures directes d'état de page — non couvert au jalon A.
- **Rechercher/Remplacer** n'est pas instrumenté (coupe retenue par le critic pass 2, consigne
  mineure 6) : ses deux sites d'écriture (`app/controllers/search_replace.py:956-964`, `:986-993`)
  sont rattrapés par le pré-état au flush suivant, avec l'étiquette `manual` plutôt qu'une origine
  dédiée.
- **Journal partagé possible** entre un bloc supprimé encore référencé dans un `image_states`
  périphérique et son bloc recréé par annulation : aliasing amont de `RectCommandBase`
  (`app/ui/commands/base.py:174-178`), volontairement non dé-aliasé (voir alternatives rejetées) —
  peut produire une entrée fantôme jusqu'au prochain `save_image_state`.
- Au-delà de **2 000 caractères**, un champ n'a plus d'historique (champ écrit, aucune entrée,
  un seul avertissement journalisé, pas par occurrence).
- Une correction qui ne change **que la casse** n'est jamais journalisée (dédoublonnage par
  `casefold`, nécessaire à cause de B5 — `set_upper_case` s'applique après chaque traduction).
- La borne de volumétrie (≤ 8 000 caractères par bloc) n'est garantie **qu'après le flush de la
  page courante** — non bornée pour une page jamais rouverte dans la session (append en place sans
  prune tant que `flush_pending` n'est pas passé).
- Dans l'**app d'origine** (si un `.ctpr` du fork y est rouvert) : `TextBlock.deep_copy` amont ne
  recopie pas `versions` (champs recopiés un par un) — dégradation silencieuse, sans plantage,
  conforme à la contrainte de compatibilité ascendante de la spec 03 §4.1.

**Conséquences générales** : toute nouvelle écriture de `blk.text`/`blk.translation` sur un bloc
vivant doit passer par `modules.history.versions.set_text` (ou `snapshot`/`record_diff` pour un
processeur qui écrit le champ lui-même) — règle ajoutée à `CLAUDE.md`.

## ADR-013 — Voir l'original : voile peint par la vue, jamais par la scène

Date : 2026-09-19
Statut : Adoptée (jalon B de la spec 03, test manuel de Philippe en attente)

**Contexte** : `specs/03-inventaire.md` §4 constate qu'aucune couche n'est masquable dans le
viewer (E1, « absent ») — impossible de voir la page d'origine sans quitter l'app. Chaîne de
conception : architect → critic pass 1 (« Architect must revise ») → conception v2 → critic
pass 2 (« Acceptable to proceed », 2 consignes bloquantes) → implementer.

**Bloquants du critic pass 1** : conception v1 basée sur une touche de composition du clavier Mac
français comme déclencheur (Alt/Option produit des accents, ex. Alt+O → œ) — conflit direct avec
la saisie de texte ; voile « collé » en cas de relâchement d'Alt manqué par l'app (perte de focus,
feuille native) ; clics avalés par le mécanisme envisagé. Retenu en v2, en plus du bouton : Alt
reste le déclencheur (cohérent avec l'usage courant « touche maintenue pour comparer ») mais
désarmé de façon défensive (désactivation de fenêtre, changement d'état applicatif, resynchronisé
sur l'état réel du clavier au prochain événement) et inhibé pendant toute saisie de texte.

**Consignes bloquantes du critic pass 2, appliquées** :
1. Ne jamais peindre le voile sans photo chargée ni en mode webtoon, quel que soit l'état du
   bouton (`self.webtoon_mode or self.photo.pixmap().isNull()` revérifié à chaque
   `drawForeground`, jamais une seule fois à l'armement).
2. Resynchroniser Alt sur l'état réel du clavier (`QGuiApplication.queryKeyboardModifiers()`) à
   chaque `KeyPress`/`KeyRelease`/`MouseButtonPress` suivant, pour rattraper un relâchement manqué
   par l'app.

**Décision** — `modules/view/original.py` (nouveau paquet, importe PySide6, seul point d'import
dans `app/ui/main_window/window.py` et `app/ui/main_window/builders/workspace.py`) :
- `OriginalViewImageViewer(ImageViewer)` peint le voile dans `drawForeground` — fond opaque
  (`backgroundBrush()`) puis la photo d'origine (`self.photo`, jamais copiée ni mise en cache) par-
  dessus tous les items de la scène, revue à chaque repaint. **Rien n'est modifié dans la scène** :
  `scene.render()` (export image/CBZ/PDF/PSD, « enregistrer l'image courante » Cmd+E) ignore ce
  voile par construction — mesuré, aucune levée temporaire nulle part dans le code.
- Deux déclencheurs indépendants, combinés par `_veil_active()` : bouton **Original** (checkable,
  colonne Outils à côté de Pan, hors outils exclusifs) et touche **Alt/Option** maintenue, armée
  seulement si :

  | Condition | Vérifiée par |
  |---|---|
  | Espace de travail actif | `_workspace_is_active` (recopié de `ShortcutController`) |
  | Aucune fenêtre modale | `QApplication.activeModalWidget() is None` |
  | Fenêtre principale active | `main.isActiveWindow()` |
  | Aucune saisie en cours | `_is_text_input_focused` (champ éditable focalisé) et `_any_text_item_editing` (bulle en édition sur le canevas) |
  | Pas en mode webtoon | `viewer.webtoon_mode` |

  Désarmée sur relâchement d'Alt, désactivation de fenêtre, changement d'état applicatif, et
  resynchronisée sur l'état réel du clavier au premier événement suivant (consigne bloquante 2).
  Le bouton s'enfonce visuellement pendant Alt (`setDown`).
- Aucun clic n'est avalé : le filtre d'événements retourne toujours `False`, les éléments de la
  scène restent cliquables bien qu'invisibles sous le voile (dit dans l'infobulle du bouton).
- Webtoon : voile jamais peint (garde dans `drawForeground`, indépendante de l'état du bouton),
  bouton grisé au changement de mode (cosmétique — la garde qui fait foi est dans
  `drawForeground`, jamais le seul signal `toggled`, étouffé par `blockSignals` pendant la bascule
  webtoon).
- Rien n'est persisté (`.ctpr`, QSettings) — état de vue pure, recréé vide à chaque lancement.
- 5 lignes `# fork:` (`window.py` 2, `workspace.py` 2, `tests/conftest.py` 1). Raccourci clavier
  configurable envisagé puis coupé : aurait coûté ~5 lignes amont supplémentaires pour un 3e
  déclencheur, sans besoin exprimé.

**Alternatives rejetées** :
- **`setVisible` par item** (masquer/révéler chaque item de patch/texte/tracé) : rejetée — casse
  « enregistrer l'image courante » (qui rend la scène telle quelle, `setVisible` y serait visible),
  exige des hooks sur chaque site de création d'item, complique undo/redo (état de visibilité à
  restaurer) et n'est pas couvert en webtoon (chunks recréés dynamiquement).
- **Vue de comparaison séparée** (deuxième `QGraphicsView` synchronisée) : rejetée, ~400 lignes
  estimées pour la synchronisation (zoom, pan, sélection) sans bénéfice sur le besoin exprimé
  (comparer d'un geste, pas côte à côte en continu).
- **Widget de recouvrement enfant du viewport** (blit direct du viewport plutôt que peinture dans
  `drawForeground`) : rejetée — pas de signal de transformation fiable sur `QGraphicsView` pour
  resynchroniser la position/le zoom du recouvrement à chaque frame.
- **Espace comme déclencheur** (plutôt qu'Alt) : rejetée — Espace déclenche les boutons focalisés
  et tape un caractère dans les champs, pire que le conflit Alt/composition qu'il visait à éviter.

**Conséquences assumées** :
- Ferme le critère §6.2 de la spec 03 (« masquer le texte traduit d'un clic et voir l'original »).
- Laisse ouverte la **visibilité par couche** (voir la page nettoyée sans texte, par exemple) :
  impossible avec un voile tout-ou-rien — exigerait le mécanisme `setVisible` par item écarté
  ci-dessus, et de reboucher le trou qu'il ouvre dans « enregistrer l'image courante ». Jalon
  ultérieur, seulement si demandé par Philippe.
- Portée strictement page originale vs état courant ; pas de comparaison patch par patch ni de
  calque de nettoyage isolé.

**Tests** : `tests/test_original_view.py`, 22 tests `--gui` offscreen — export et `save_state`
identiques octet pour octet avec/sans voile (`viewport().grab()` diffère, lui), bouton/touche/
auto-repeat/relâchement, changement de page avec contenu vérifié, rendu et nettoyage pendant le
voile + undo/redo, aucune clé nouvelle dans l'état sauvegardé, webtoon et absence d'image → rien
peint, désarmement sur désactivation de fenêtre/modale, resynchronisation sur l'état clavier réel,
`save_current_image` bout en bout identique, Alt inhibé en saisie (y compris caractère composé
« œ »). Suite complète : 213 tests hors GUI inchangés, 245 avec `--gui` + l'échec amont connu de
`test_app.py`. Limite de test documentée : sous le pilote offscreen, le viewport de la fenêtre
sans bordure reste à 100×30 px — les tests qui comparent des pixels utilisent une vue autonome,
pas la fenêtre principale.

## ADR-014 — État d'avancement par page : déduction pure, aucune persistance

Date : 2026-09-22
Statut : Adoptée (jalon 1 de la spec 04, test manuel de Philippe en attente)

**Contexte** : `specs/04-refonte-interface.md` §5 jalon 1 demandait initialement « écriture de
l'état au passage de chaque étape » et « persistance : clé supplémentaire dans `image_states` ».
Chaîne de conception : architect → critic pass 1 (« Architect must revise », 1 bloquant M1, 3
majeurs) → arbitrage de Philippe (option A) → conception v2 → critic pass 2 (« Acceptable to
proceed », 7 mineurs) → implementer → tester (OK) ; security-reviewer non déclenché (module lecture
seule, aucun réseau/fichier/sous-processus).

**Options considérées** :
- **A (retenue)** : déduction pure à l'affichage, deux statuts par étape — FAITE (compteur > 0) /
  ABSENTE — jamais rien écrit ni persisté. Format `.ctpr` inchangé dans les deux sens.
- **B (rejetée après revue du critic)** : un drapeau persisté « étape lancée » (troisième statut
  VIDE) pour distinguer « jamais lancée » de « lancée sans résultat ». Rejetée : le drapeau mentait
  après une ré-détection (drapeaux OCR/traduction jamais invalidés alors que les blocs sont neufs),
  s'affichait VIDE pendant l'opération elle-même, divergeait entre page seule / multi-pages / lot
  selon le chemin d'écriture, et pouvait viser la mauvaise page si l'utilisateur navigue pendant le
  traitement (voir défauts amont n°1 et n°2 ci-dessous). Coût ~22 lignes amont pour une garantie
  qui ne tenait pas. Le signal « lancée sans résultat » est reporté au jalon 3 de la spec 04, sous
  forme de message à la complétion d'une étape plutôt que d'un état persisté.

**Décision** — `modules/pagestate/` (nouveau paquet) :
- `progress.py` (pur) : `STEPS = ("detect", "ocr", "translate", "clean", "render")`, dataclass
  figée `PageProgress` + `done(step)`, `compute_progress`.
- `collect.py` (pur, duck typing, aucun import PySide6) : `live_path(main)` — renvoie le chemin de
  la page vivante, ou `None` si webtoon, si `_batch_active`, si `curr_img_idx` hors
  `[0, len(image_files))`, ou si `image_data[page]` est `None` (page pas encore chargée — évite le
  clignotement « tout vide » à l'ouverture d'un projet) ; `page_progress(main, path)` — lit la page
  courante sur le **vivant** (`main.blk_list`, `main.image_patches`, `main.image_viewer`) si
  `live_path(main) == path`, sinon dans `image_states[path]`.
- `ui.py` (seul fichier du paquet à importer PySide6) : `PageStateDelegate`, enveloppe par
  **composition** autour du délégué amont de la liste de pages (`page_list.itemDelegate()`, jamais
  d'héritage de `PageListItemDelegate`) — peint une piste de cinq segments par-dessus, `sizeHint`
  délégué (liste à `setUniformItemSizes(True)`). `_Refresher` étranglé à 30 ms sur signaux
  (`undo_group.indexChanged`, `render_state_ready`, `patches_processed`, `image_skipped`,
  `progress_update`, `s_text_edit`/`t_text_edit.textChanged`) + chien de garde à 500 ms sur la
  signature des lignes visibles (couvre les écritures non signalées : OCR/traduction manuels,
  écritures multi-pages directes, Segmenter, fin de lot). `attach_page_state(main)` entièrement
  sous `try/except` : l'app démarre sans pastilles si l'attache échoue.
- **Définitions des cinq compteurs** : detect = nb blocs ; ocr / translate = nb blocs avec
  `text` / `translation` non vide après strip ; clean = `len(main.image_patches.get(path, []))`
  (source unique, jamais de lecture de `png_path`) ; render = `text_items_state` pour une page lue
  dans `image_states`, items de `image_viewer.text_items` présents dans la scène pour la page
  vivante (compte exactement ce que `save_state` persiste).
- **Attache en fin de `ComicTranslate.__init__`**, pas dans `workspace.py` : `workspace.py`
  s'exécute pendant `super().__init__`, avant la création de `undo_group`, `image_states`,
  `blk_list`, `image_patches` — plantage au démarrage constaté en revue (bloquant M1 du critic
  pass 1).
- Amont touché : `controller.py` (2 lignes `# fork:`, import + `attach_page_state(self)` juste
  après `self.connect_ui_elements()`), `tests/conftest.py` (1 ligne `# fork:`,
  `test_pagestate_ui.py` ajouté à `_GUI_ONLY_FILES`). **3 lignes, 2 fichiers.** Zéro ligne dans
  `list_view.py`, `image.py`, `manual_workflow.py`, `text.py`, `pipeline/*`, `app/projects/*`.

**Constat de conception corrigé en cours de route** : l'affirmation initiale selon laquelle les
`TextBlock` seraient partagés (aliasing superficiel) entre `main.blk_list` et
`image_states[courante]['blk_list']` était **fausse** — copies constatées en `box.py:274`,
`:298-299`, copies profondes `manual_workflow.py:112`/`:195`, `block_detection.py:63`. D'où la
règle de source (`live_path`) plutôt qu'une lecture uniforme de `image_states`.

**Tests** : `tests/test_pagestate.py` (27 tests hors GUI), `tests/test_pagestate_ui.py` (15 tests
`--gui`). `uv run pytest -q` → 240 passed ; `--gui` → 287 passed, 3 skipped, 1 failed
(`tests/test_app.py`, échec amont connu). Ruff OK. Coût du tick du chien de garde : médiane
0,53 ms mesurée sur 242 pages × 30 blocs (~60 lignes visibles). Test clé de non-écriture : octets
d'un `.ctpr` réel (`save_state_to_proj_file_v2`) identiques SHA-256 avant/après une rafale de
peintures, ticks et rafraîchissements — lecture seule prouvée, pas seulement affirmée.

**Conséquences et limites assumées (à ne pas « corriger par surprise »)** :
- Pastilles indépendantes, pas une barre de progression monotone : un lot annulé peut laisser une
  page « nettoyée » seule sans blocs (patchs posés `batch_processor.py:327` avant `blk_list`
  `:441`) — c'est la vérité des données, pas un bug d'affichage.
- Pendant un lot, la page courante est lue dans `image_states` (`live_path` renvoie `None` si
  `_batch_active`) : du travail non enregistré sur cette page fait reculer ses pastilles jusqu'à la
  fin du lot.
- Branche lot « aucun bloc détecté » (`batch_processor.py:191-195`) : n'écrit pas `blk_list`, les
  anciens blocs restent affichés FAITE.
- Lot en échec OCR/traducteur : état de la page inchangé, la raison est dans le rapport de lot
  (§2 de la spec 04).
- Import PSD : seule « rendue » s'allume (`blk_list` vide après import).
- Webtoon : lecture `image_states` seulement, peut être en retard — hors périmètre (comme pour les
  specs 02 et 03).

**Défauts amont découverts en cours de conception, non corrigés (candidats PR amont, spec 00 §5)** :
1. **Navigation pendant un lot → corruption de page** : `batch_processor.py:97` capture
   `file_on_display` au début du traitement d'une page ; si l'utilisateur navigue, `:450-451` fait
   `main.blk_list = blocs de A` alors que B est affichée ; la navigation suivante
   (`save_image_state(B)`, `image.py:1021-1031`) écrit les blocs de A dans `image_states[B]`. Non
   reproduit en réel, déduit du code et confirmé par deux revues.
2. **Même défaut hors lot** : opérations multi-pages (Reconnaître/Traduire/Détecter sur une
   sélection) avec `context["current_file"]` périmé si l'on navigue pendant l'opération
   (`manual_workflow.py:185-196`, `:282-286`, `:392-396` ; `text.py:904-913`).
3. **`_batch_active` peut rester bloqué à `True`** : lot mis en file derrière un autosave
   (`projects.py:431`, `controller.py:649`/`:673`), clic Annuler qui vide la file
   (`task_runner.py:155`) avant démarrage → `on_batch_process_finished` jamais appelé ; bouton
   Traduire grisé et barre de progression affichée jusqu'à la fermeture de l'app.
4. **Perte du rendu de lot sur page insérée** : page insérée avec `viewer_state = {}`
   (`image.py:452-458`), le lot n'y ajoute que `text_items_state` et `push_to_stack`
   (`batch_processor.py:428-434`), `viewer.load_state` lève `KeyError` sur `state['rectangles']`
   (`image_viewer.py:546`) après avoir vidé la scène, et la navigation suivante persiste
   `text_items_state = []`. Touchera le jalon 4 de la spec 04 (lot rendu visible).

**Alternatives rejetées** :
- **Propriété calculée mise en cache par page** (recalcul à la demande, invalidée par signal) :
  rejetée à ce stade — la mesure (0,53 ms/tick) ne justifiait pas la complexité d'un cache invalidé
  correctement sur tous les chemins d'écriture identifiés.
- **Instrumenter `on_manual_finished`** (1 ligne amont pour rendre l'OCR/la traduction manuels
  instantanés au lieu d'attendre le chien de garde à 500 ms) : écartée, 1 ligne amont pour gagner
  0,5 s de latence perçue — à réintroduire seulement si Philippe trouve la latence gênante à
  l'usage.

**Amendement 2026-09-27** : le bouton **Original** est repositionné par `modules/shell/` en
surimpression en haut à droite de la page (spec 04 jalon 2, sous-étape 2a, ADR-015) — le
mécanisme du voile lui-même (peinture dans `drawForeground`, déclencheurs bouton/Alt) est
inchangé.

## ADR-015 — Nouvelle disposition par reparentage des widgets amont

Date : 2026-09-27
Statut : Adoptée (jalon 2 de la spec 04, sous-étape 2a livrée, test manuel de Philippe en attente)

**Contexte** : spec 04 jalon 2, « la coquille de la maquette, sans aucune fonction nouvelle »
(maquette « Atelier de traduction BD », `specs/maquette-atelier.html`). Les contrôleurs lisent les
widgets par nom (`text.py:34-42` capture des références, ~400 lectures dans le dépôt) — toute
recréation d'objet casserait ces références.

**Options considérées** :
- **A (retenue)** : le constructeur amont `_create_main_content` s'exécute tel quel ; le shell
  **reparente les mêmes objets** (jamais recréés) dans une disposition à 3 colonnes.
- **B (rejetée)** : recréer les widgets dans la nouvelle disposition. Rejetée — casserait les ~400
  lectures par nom des contrôleurs, coût de correction disproportionné et fragile (toute lecture
  oubliée plante silencieusement au premier usage).
- **C (rejetée)** : `QDockWidget` pour chaque zone. Rejetée — moins fidèle à la maquette (barres de
  titre de dock, redocking libre non désiré), pas de gain sur le problème de reparentage.

**Décision** — `modules/shell/` (nouveau paquet) :
- `manifest.py` (pur) : noms d'attributs par zone (HEADER, PROGRESS, LEFT, CENTER, OVERLAY, PAGE,
  BUBBLE, RENDER, TOOLS, PARKED vide en 2a, EXTERNAL `undo_tool_group`) — **seul fichier à revoir
  au rebase amont**.
- `context.py` (pur), `panel.py` (squelette du panneau droit), `layout.py`
  (`build_workspace_shell(main, legacy_content)`) — orchestration du reparentage.
- Disposition : pages + recherche à gauche, `central_stack` au centre avec le badge Original en
  surimpression en haut à droite (enfant du conteneur central, hors scène/viewport/
  `drawForeground` → absent de tous les exports), panneau droit en `QSplitter` vertical (Source /
  Traduction, rangée Historique + Set for all, groupe Rendu du texte, groupe Outils en bas, 3
  rangées, décision de Philippe 2026-09-26).
- **Tout-ou-rien** : valider sans rien toucher → construire à vide → déplacer avec journal (index
  relevé au moment du déplacement) → finaliser (ancien contenu parqué caché dans
  `main._shell_legacy`, parent `main`, jamais détruit). Toute erreur → retour arrière exact +
  **repli visible** (bandeau « Nouvelle disposition indisponible… », `main._shell_active = False`,
  `main._shell_failure`) — jamais un échec silencieux.
- **Interrupteur `COMIC_SHELL=0`** : relance l'app dans l'ancienne disposition sans bandeau, pour
  départager un défaut du shell d'un défaut préexistant de l'amont (a servi le 2026-09-27, voir
  ADR-016).
- Amont touché : `app/ui/main_window/window.py` (2 lignes `# fork:` : import + construction du
  shell), `tests/conftest.py` (1 ligne). **Zéro ligne** dans `workspace.py`, `nav.py`,
  `controller.py`, les contrôleurs, `pipeline/`. `modules/view/original.py` : docstring seulement
  (le shell repositionne le bouton, mécanisme inchangé — voir amendement ADR-013 ci-dessus).

**Chaîne de conception** : architect (options A/B/C) → critic pass 1 (« Architect must revise » :
bloquant — bouton Original dans l'en-tête contraire à la maquette ; majeurs — focus déplacé par
`QStackedLayout`, Cancel actif au repos, perte de l'issue de secours du défaut amont n°3
(ADR-014), colonne d'outils verticale mal justifiée, repli partiel, garde aveugle aux widgets
locaux, affirmation webtoon erronée) → décisions de Philippe (outils en bas du panneau droit,
aucun `.ctpr` webtoon) → conception v2 → critic pass 2 (« Acceptable to proceed », conditions :
focus lu via `window().focusWidget()`, 2b-bis jamais pendant un lot et comparaison par `==`, index
relevé au déplacement, badge repositionné/masqué au départ/`raise_()`, fixture sans effet de bord)
→ implementer (2a) → tester (OK, 12 tests ajoutés, régression de hauteur mesurée et corrigée) →
correctif implementer → test manuel de Philippe en attente.

**Mesures** (offscreen) : champs texte 136/135 px à 1225×797 (Air 13" par défaut, contre 120 px
fixes avant), 84/83 px à 1066×693 (« Texte plus grand », sous les 120 px d'avant — la sous-étape
2c retirera les listes de langue de la section Bulle pour regagner cette hauteur). Première
version à 114/62 px corrigée (libellé et liste de langue mis sur la même rangée, espacements
resserrés). Nom de police tronqué corrigé (police seule sur sa rangée).

**Tests** : `tests/test_shell.py` (7, hors GUI, dont non-import PySide6), `tests/test_shell_ui.py`
(30, `--gui`) : garde de couverture sur les descendants interactifs de `_shell_legacy` (prouvée par
injection d'un bouton non listé), repli simulé, retour arrière par injection d'erreur à 4 points
(ordre des layouts, `QSplitter` et `QScrollArea` compris), badge (hors viewport/scène, masqué sur
l'écran vide, repositionné quand la barre de défilement apparaît, `save_state` et rendu identiques
badge coché ou non), undo/redo de la barre de titre, recherche Ctrl+F, thème dayu appliqué aux
widgets déplacés, identité des widgets, hauteur des champs ≥ 120 px à 1225×797.

**Conséquences et reste à faire** :
- Maquette versionnée : `specs/maquette-atelier.html`.
- **2b** (radios et interrupteur webtoon parqués cachés, fonctions de mode neutres, Cancel grisé
  au repos et actif seulement pendant un lot, `webtoon_mode = False` en tête de
  `update_ui_from_project`), **2b-bis** (issue au défaut amont n°3 de l'ADR-014 — correction de 3
  lignes dans `task_runner.py`, qui ne doit jamais se déclencher pendant l'exécution d'un lot,
  sinon variante sans ligne amont par scrutation ; **décision de Philippe en attente**), **2c**
  (pile Page/Bulle, observateur, règle de focus lue sur `window().focusWidget()` avant
  `setCurrentIndex`, test « fenêtre inactive »).
- « Source jamais vidée » (annotation 4 de la maquette) : **reporté**, défauts amont
  (`image.py:1131`, `text.py:929`, `rect_item.py:62-63`) non corrigés.

## ADR-016 — Analyse du texte sur l'image d'origine (hotfix)

Date : 2026-09-27
Statut : Adoptée (hotfix)

**Contexte** : test manuel de Philippe sur la nouvelle disposition (2a) — après quelques cycles
Détecter/Reconnaître/Traduire/Segmenter/Nettoyer/Rendre, « plus rien ne fonctionne » : boutons
cliquables sans effet, aucune erreur au journal. Départagé de la nouvelle disposition par
`COMIC_SHELL=0` : le défaut est préexistant à l'amont, indépendant du shell.

**Diagnostic** (lanceur de diagnostic hors dépôt qui trace la file de tâches et les clics) : la
file n'est pas bloquée, chaque opération démarre et se termine. « Détecter » sur une page déjà
nettoyée passait de 10 blocs à **0** : `pipeline/block_detection.py` analysait
`image_viewer.get_image_array()`, qui inclut par défaut les patchs de nettoyage — le texte anglais
n'est plus dans l'image, la détection ne trouve rien et **remplace les blocs existants par zéro**.
Ensuite « Reconnaître » n'a plus de rectangle (garde silencieuse déjà connue, `pipeline/
ocr_handler.py:24`) et « Rendre » avec 0 bloc efface les textes rendus. Récupération : Cmd+Z.

**Décision** : `get_image_array(include_patches=False)` aux 5 appels qui analysent le texte de la
page courante — `pipeline/block_detection.py` (détection), `pipeline/ocr_handler.py`
(reconnaissance, et clé de cache OCR désormais stable après nettoyage), `pipeline/
translation_handler.py` (image de contexte du traducteur et clé de cache), `app/controllers/
manual_workflow.py` ×2 (segmentation : masque du texte à nettoyer, page seule). 5 lignes
`# fork:` dans 4 fichiers.

**Non modifié à dessein** : `pipeline/inpainting.py:76` — le nettoyage peint par-dessus les
patchs déjà posés et doit voir l'image déjà nettoyée, pas l'original. Le traitement par lot lisait
déjà l'image depuis le fichier (donc l'original), non affecté.

**Tests** : `tests/test_analysis_on_original.py` (`--gui`, 1 ligne `# fork:` dans
`tests/conftest.py`) : garde statique sur les 5 appels + test réel (patch blanc posé dans la
scène, la détection voit la photo d'origine) ; vérifié qu'il échoue sans le correctif.
`tests/test_block_versions_handlers.py` adapté (faux lecteur d'image à la nouvelle signature).
Suites : 247 passed hors GUI ; `--gui` 326 passed, 3 skipped, 1 failed (`test_app.py`, échec amont
connu).

**Piège d'implémentation** : `app/controllers/manual_workflow.py` a des fins de ligne mixtes
(CRLF, CR, LF) — l'éditer en octets, sinon tout le fichier apparaît modifié dans le diff.

**Conséquences** : règle ajoutée à `CLAUDE.md` — toute analyse du texte de la page (détection,
OCR, segmentation, traduction) lit `get_image_array(include_patches=False)` ; seul le nettoyage
lit l'image avec patchs.
