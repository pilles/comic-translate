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

**Amendement 2026-09-27 — sous-étape 2b livrée** : parcage effectif de `manual_radio`,
`automatic_radio`, `webtoon_toggle` (zone `PARKED` de `manifest.py`, vide en 2a, peuplée en 2b) —
`layout.py` ne les déplace plus, `_hide_parked_widgets(main)` les masque dans `_finalize` et dans
le repli ; sous `COMIC_SHELL=0`, seul `webtoon_toggle` est masqué (les radios, devenues inoffensives
une fois `controller.py` neutralisé, restent visibles). `controller.py` (6 lignes `# fork:`) :
`batch_mode_selected` et `manual_mode_selected` produisent désormais le même état de repos (6
étapes + Translate All actifs, Cancel grisé) quel que soit le réglage QSettings `main_page/mode` ;
`_run_batch_for_paths` grise les étapes pendant le lot, `on_batch_process_finished` les réactive et
regrise Cancel. `app/controllers/projects.py` (1 ligne `# fork:`) : `self.main.webtoon_mode = False`
en tête de `update_ui_from_project` (chargement normal et récupération) — le webtoon n'étant pas
pris en charge, un `.ctpr` webtoon peut lever `KeyError` (`image_viewer.py:546`), non corrigé.
Tests : ~19 ajoutés à `tests/test_shell_ui.py` (widgets parqués masqués/vivants/sous
`_shell_legacy`, fonctions de mode neutres, lot factice avec état de repos avant/pendant/après,
`cancel_current_task`, démarrage identique quel que soit `main_page/mode`, `COMIC_SHELL=0` ne masque
que l'interrupteur webtoon). Suites : 248 passed hors GUI ; `--gui` 346 passed, 3 skipped, 1 failed
(`test_app.py`, amont connu). **2b-bis** (correctif du défaut amont n°3 de l'ADR-014,
`task_runner.py`) décidée par Philippe le 2026-09-27, livraison à venir (commit séparé) — garde-fou :
ne jamais se déclencher pendant l'exécution d'un lot, comparaison du rappel par `==`.

**Amendement 2026-09-28 — sous-étape 2c livrée, jalon 2 clos** : panneau de droite contextuel,
`panel.py` réécrit — `QStackedWidget` à deux pages : **Page** (rien de sélectionné : Langue source
+ `s_combo`, Langue cible + `t_combo`, `set_all_button`, aide « Sélectionnez une bulle pour voir son
texte ») et **Bulle** (une bulle sélectionnée : `QSplitter` vertical « <langue> · reconnu » +
`s_text_edit` / « <langue> · traduction » + `t_text_edit`, bouton Historique). « Rendu du texte » et
« Outils » restent communs, sous la pile (double usage inchangé : sans sélection, ils règlent le
prochain « Rendre »).

`modules/shell/context.py` (pur) : `panel_context(curr_tblock, curr_tblock_item, search_visible)`
→ `CONTEXT_PAGE` / `CONTEXT_BUBBLE`. `modules/shell/watcher.py` (nouveau, importe PySide6) :
`_ContextWatcher` bascule `panel.stack` — déclencheurs `image_viewer.rectangle_selected`,
`image_viewer.clear_text_edits`, `page_list.currentItemChanged`, filtre de relâchement de souris sur
le viewport, filtre Show/Hide sur `search_panel`, regroupés par `QTimer.singleShot(0)` (un seul en
attente à la fois) ; chien de garde à 200 ms qui rattrape les affectations directes sans signal
(`curr_tblock`/`curr_tblock_item` posés par ~20 sites de contrôleurs) — sort immédiatement si le
panneau n'est pas visible, coût mesuré médiane 0,0023 ms/tick. `setCurrentIndex` appelé seulement au
changement d'index ; les deux libellés de langue (page Bulle) sont relus à chaque évaluation (pas de
signal fiable sur `s_combo`/`t_combo`, changés sous `blockSignals`).

**Règle de focus** (condition du critic) : avant tout `setCurrentIndex`, lecture de
`window().focusWidget()` — jamais `QApplication.focusWidget()`, qui renvoie `None` quand
l'application est inactive et masquerait justement le cas à traiter. Si le focus est dans la section
sortante → `image_viewer.setFocus()` (ou `clearFocus()` si la vue est cachée, le focus tombe alors à
`None`, jamais sur une liste de langue) ; le shell ne donne jamais lui-même le focus à la section
entrante. Évite qu'Espace sur « Set for all » écrase les langues de tout l'album, ou qu'une lettre
tapée change la langue source. Recherche Ctrl+F : `setFocus` sur un champ de la page cachée de la
pile est accepté par Qt et restitué à la bascule (vérifié par test) — `app/.../search_replace.py`
non touché.

Zéro ligne amont. Champs texte en contexte Bulle : 161/160 px à 1225×797 (136 en 2a, 120 avant les
sous-étapes du jalon 2). Tests : `tests/test_shell.py` 15 (hors GUI), `tests/test_shell_ui.py` ~75
(`--gui`, dont une analyse AST de non-écriture, un chien de garde qui rattrape les affectations
directes sans signal, le focus en fenêtre inactive, et le cas écran vide). Suites : 263 passed hors
GUI ; `--gui` (`.venv/bin/python -m pytest`) 385 passed, 3 skipped, 1 failed (`test_app.py`, amont
connu).

Piège d'outillage (ajouté à `CLAUDE.md`) : le hook de formatage (`ruff --fix` en `PostToolUse`)
supprime un import ajouté dans une édition et utilisé seulement dans une édition suivante — ajouter
l'import et son premier usage dans la **même** édition, et vérifier par `grep` après coup. Autre
piège : les tests du chien de garde exigent la fenêtre affichée (`main.show()`), sinon il sort
immédiatement par construction (garde `panel.stack.isVisible()`).

**Jalon 2 clos** (2a, 2b, 2b-bis, 2c livrées, validation manuelle de Philippe reçue pour 2b et 2c le
2026-09-28). Reporté, toujours ouvert : « source jamais vidée » (annotation 4 de la maquette ;
défauts amont `image.py:1131`, `text.py:929`, `rect_item.py:62-63`, non corrigés).

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

## ADR-017 — Sauts de ligne du modèle de traduction remplacés par des espaces (hotfix)

Date : 2026-09-27
Statut : Adoptée (hotfix, commit `566740b`)

**Contexte** : cas réel page 011 de l'album de test — texte anglais reconnu sur une seule ligne,
`translategemma` renvoie une traduction avec un saut de ligne en pleine phrase (« … DE SON PÈRE\nET
VOLÉ … ») ; le rendu respectait ce saut de ligne, coupant la bulle à un endroit arbitraire choisi
par le modèle plutôt que par la largeur réelle de la bulle.

**Décision** : `set_texts_from_json` (`modules/utils/translator_utils.py`) remplace tout saut de
ligne (et les blancs autour, `\r`/`\n` compris) par une espace unique avant d'écrire
`blk.translation` (`re.sub(r"\s*\n\s*", " ", value).strip()`). 4 lignes `# fork:`. Règle : c'est au
rendu de couper le texte selon la largeur de la bulle, jamais au modèle de traduction.

**Conséquences** : les traductions déjà enregistrées dans des projets existants ne sont pas
modifiées rétroactivement — seules les traductions produites après ce correctif en bénéficient.
Test : `tests/test_set_texts_from_json.py::test_llm_line_breaks_become_single_spaces`.

## ADR-018 — Plantage natif PySide6/Shiboken6 dans les tests de lot : pas de correctif applicatif

Date : 2026-09-27
Statut : Constatée, non corrigée (défaut de bibliothèque tierce, pas du fork)

**Contexte** : `Fatal Python error: Segmentation fault` intermittent dans les tests de lot de
`tests/test_shell_ui.py` (sous-étape 2b). Pile Python : `app/ui/dayu_widgets/tool_button.py:57`
(`MToolButton.changeEvent` crée un `QGraphicsOpacityEffect` en passant à l'état grisé) déclenché par
`controller.py` (`save_as_project_button.setEnabled(False)`, bouton de la barre de navigation amont,
non déplacé par le shell).

**Preuve native** : 4 rapports identiques (`~/Library/Logs/DiagnosticReports/python3.12-*.ips`),
plantage dans `PySide::SignalManager::retrieveMetaObject` ← `Sbk_QGraphicsOpacityEffect_Init` ←
`changeEvent` ← `QWidgetPrivate::setEnabled_helper` — construction d'un `QObject` pendant la dépêche
d'un autre événement. Bug de **PySide6/Shiboken6 6.11.2**, pas du fork ni de `dayu_widgets`.

**Mesures** : `uv run pytest` sur les 4 tests de lot ≈ 17 % d'échec (11/65) ; `.venv/bin/python -m
pytest` 0/30 échec ; un seul test par processus 0/35 ; 15 tests rejoués dans un même processus
0/60 ; `COMIC_SHELL=0` 0/65. La nouvelle disposition (2a/2b) augmente la probabilité d'apparition
(ordre de construction des widgets) sans en être la cause. Hypothèse « préchauffer l'effet dans le
shell » testée puis retirée : aucun effet mesuré (5/40). Hypothèse initiale (interrupteur webtoon
masqué) fausse et abandonnée, `controller.py` non modifié pour elle.

**Décision** : pas de correctif applicatif — c'est un défaut de PySide6/Shiboken6, pas du code du
fork. Consigne de lancement : `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --gui` plutôt
que `uv run pytest --gui` (réduit l'échec à 0 sur les mesures faites). Candidat à signaler en amont
de PySide6 si reproductible hors fork. `lldb` inutilisable ici (« Not allowed to attach », macOS) —
les rapports du crash reporter système ont suffi au diagnostic.

**Conséquences assumées** :
- Application réelle jugée **peu probable** (une seule fenêtre par lancement ; le plantage n'a été
  observé qu'avec plusieurs instances de fenêtre créées/détruites dans le même processus, comme le
  fait `qtbot` dans les tests) — non formellement exclu, à surveiller si un plantage similaire
  apparaît un jour en usage réel.
- `test_pagestate_ui.py::test_watchdog_tick_median_cost_under_one_millisecond` peut échouer sous
  charge (mesure de temps CPU), passe isolé — sans rapport avec ce défaut, à ne pas confondre.

## ADR-019 — Défaut amont n°3 corrigé : fin d'un lot annulé avant démarrage

**Date** : 2026-09-27. **Statut** : accepté (décision de Philippe, spec 04 jalon 2, sous-étape 2b-bis).

**Contexte.** Défaut amont n°3 (ADR-014) : un lot mis en file derrière une autre opération
(typiquement un autosave) puis annulé avant d'avoir démarré. `cancel_current_task` vide la file ;
le `finished_callback` du lot (`on_batch_process_finished`) n'est donc jamais appelé et
`_batch_active` reste `True` pour toute la session : Translate All et Cancel grisés, étapes grisées
(depuis la 2b), barre de progression affichée, sauvegarde automatique coupée en silence
(`autosave_project` sort tant que `_batch_active`). Avant la 2b, la radio Automatique servait
d'issue de secours ; elle a disparu.

**Décision.** Corriger dans `app/controllers/task_runner.py` (10 lignes `# fork:`) :
`_process_next_operation` mémorise l'opération en cours (`self._current_operation`) ;
`cancel_current_task` repère, avant de vider la file, un lot en file (`finished_callback ==
main.on_batch_process_finished`) et, après, planifie `on_batch_process_finished` par
`QTimer.singleShot(0, main, …)` — sauf si l'opération en cours est elle-même un lot (il se
terminera seul ; déclencher provoquerait une fin prématurée pendant l'inférence et une double
finalisation du rapport) ou si la fenêtre se ferme (`main._is_shutting_down`, posé par `shutdown()`
avant `cancel_current_task`). Le lot annulé se termine alors comme un lot annulé à la première
page : rapport « annulé », indicateurs remis à zéro, boutons rendus, autosave rétablie.

**Pièges évités (critic).** Comparaison des rappels par `==`, jamais `is` (méthodes liées : deux
accès donnent deux objets distincts) — prouvé par mutation, le test échoue avec `is`.
`threadpool.activeThreadCount()` écarté comme critère « lot en cours » (vignettes et autosave le
faussent).

**Options rejetées.** Contournement sans ligne amont (minuteur dans le shell qui détecte l'état
bloqué) : un module d'interface aurait piloté un état de contrôleur par scrutation. Laisser tel
quel : plus d'issue sans redémarrage depuis la 2b.

**Conséquences.** `tests/test_batch_cancel_before_start.py` (7 tests hors GUI, chacun en
sous-processus avec sa propre `QCoreApplication` et un faux `main` `QObject`, pour ne pas polluer
le singleton Qt de la suite `--gui`). Limite connue : entre la fin d'une opération et le
démarrage de la suivante (quelques tours de boucle d'événements), `_current_operation` désigne
encore l'opération terminée ; une annulation dans cette fenêtre pourrait être mal classée — cas
marginal, non aggravant. Candidat PR amont. Défaut n°3 retiré de la liste des défauts ouverts de
`CLAUDE.md`.

## ADR-020 — Réinitialiser la page : option C améliorée

Date : 2026-09-28
Statut : Adoptée (spec 04 jalon 3, sous-étape 3a, validée à la main par Philippe le 2026-09-28)

**Contexte** : demande de Philippe (2026-09-28) — « rajoute un bouton "reset", ça permet de
repartir sur une page "propre" ». Cadrage initial dans `specs/04-refonte-interface.md` §5 jalon 3 :
effet = page « jamais traitée » (blocs, rectangles, texte, patchs, tracés, rendu), annulable par
Cmd+Z en une seule étape, portée = page affichée. Décisions de Philippe retenues telles quelles :
caches OCR/traduction invalidés (Traduire rappelle vraiment Ollama après reset), portée = page
affichée seule (le message nomme la page), limite « Annuler au-delà d'un reset annulé » acceptée et
à corriger plus tard (3a-ter, MAJ1 ci-dessous).

**Options considérées** :
- **A (rejetée)** : construire une macro d'annulation Qt qui rejoue toutes les commandes existantes
  (suppression de blocs, de patchs, de tracés) une par une. Rejetée — les commandes existantes ne
  couvrent pas toutes les clés d'`image_states`/`image_patches`, et empiler N commandes hétérogènes
  pour un seul clic complique l'annulation partielle sans bénéfice.
- **B (rejetée après revue du critic, « Architect must revise »)** : détacher les items Qt vivants
  de la scène (blocs, rectangles, texte) puis les rattacher à l'annulation. Rejetée — bloquant B1
  (câblage des signaux sur les items trop tôt, avant que la commande sache si elle sera annulée) et
  B2 (une macro d'annulation évaluée à l'index 0 crée un cas limite non couvert par
  `QUndoStack.canUndo()`) ; en pratique, une liste de blocs neuve à chaque réexécution aurait
  imposé de reconstruire l'ordre d'empilement des patchs à chaque fois, et des rectangles hors
  scène après un « Rendre » réapparaissaient de façon incohérente.
- **C amélioré (retenu)** : `ResetPageCommand` réécrit les clés **traitées** d'`image_states[p]`
  (`blk_list`, `brush_strokes`, `viewer_state.rectangles`, `viewer_state.text_items_state`, retrait
  de `push_to_stack`) et `image_patches[p]`, puis recharge par le chemin de navigation existant
  (`image_ctrl.load_image_state(p)`). Fidélité visée : « quitter la page et revenir », pas une
  reconstruction bit à bit de l'état initial du projet.

**Décision** — `modules/reset/` (nouveau paquet) :
- `state.py` (pur) : `blank_page_state`, `merge_processed`, `is_pristine`, `drop_cache_entries`,
  `macro_open`, `availability`, messages.
- `commands.py` : `ResetPageCommand(main, p, stack)`. Identité de la **liste** de blocs préservée
  (la liste d'origine est reposée telle quelle à l'annulation, une liste vide réutilisée à chaque
  réexécution) — les commandes de boîtes antérieures et postérieures dans la pile restent valides
  sans reconstruction. Garde par **identité de pile** (une pile orpheline après rechargement du
  projet rend la commande obsolète, rien n'est muté) et par page affichée. État réel suivi par
  `_applied` ; capture avant mutation, retour arrière sur exception. **Jamais** de `push`/
  `beginMacro`/`endMacro`/`mark_project_dirty` dans `redo`/`undo`. `in_memory_patches` (cache de
  pixels) n'est jamais réaffecté.
- `ui.py` (seul fichier du paquet à importer PySide6, importé uniquement depuis `controller.py`) :
  `request_reset` — revalidation ; page déjà vierge (lue sur l'état vivant) → message, rien poussé ;
  **macro ouverte détectée** par `count() > index() and not canRedo()` (fiable à l'index 0, d'après
  le comportement documenté de `qundostack.cpp` ; contrat figé par test) → forcément orpheline →
  confirmation explicite (« ne pourra pas être annulée »), revalidation après la modale, message
  « non annulable » ; sinon validation de l'édition en attente puis push ; focus rendu à la vue s'il
  était dans un champ de saisie (y compris les combos éditables de taille de police) pour que Cmd+Z
  fonctionne ; message non modal `MMessage` « Page N (nom) réinitialisée — Annuler (⌘Z)… », raccourci
  lu dans les réglages et affiché en texte natif.
- Bouton `MPushButton` (pas `MToolButton`, voir ADR-018 sur les effets graphiques de
  `MToolButton`) « Réinitialiser », `NoFocus`, placé après `loading` dans l'en-tête ; attaché en fin
  de `ComicTranslate.__init__` (`attach_page_reset(self)`, après `attach_page_state`) ; le shell
  expose `main._shell_header_layout` pour ce point d'attache ; absent avec `COMIC_SHELL=0` ou en
  repli. Actif ssi : les 6 étapes sont actives, la file de tâches est vide (`is_processing_queue` —
  couvre aussi l'export et l'autosave ; `loading` écarté comme critère, faux positif constaté), pas
  de lot en cours, pas de mode webtoon, espace de travail et page affichés, pile d'annulation active
  = pile de la page affichée. Recalcul déclenché par `EnabledChange` des étapes,
  `undo_group.activeStackChanged` (seul signal fiable après un changement de page asynchrone),
  `central_stack.currentChanged`, et un chien de garde à 250 ms. Clignote brièvement pendant
  l'autosave (assumé, pas corrigé).

**Amont touché** : `controller.py` (2 lignes `# fork:` : import + `attach_page_reset(self)`),
`tests/conftest.py` (1 ligne). Fork déjà en place : `modules/shell/layout.py` expose l'en-tête.

**Tests** : `tests/test_reset.py` (56, hors GUI), `tests/test_reset_ui.py` (46, `--gui`, dont 7
ajoutés par le tester : aller-retour `.ctpr` réel reset puis reset+annulation, chaîne
Détecter→Reconnaître→Traduire→Segmenter→Nettoyer→Rendre→Reset→annuler au-delà→rétablir sans
plantage, écran des réglages et écran vide, pastilles du jalon 1, image de détection sans patchs).
Suites : 319 passed hors GUI ; `--gui` 487 passed, 3 skipped, 1 failed (`test_app.py`, amont connu).

**Limites connues, assumées** :
1. **MAJ1** (acceptée par le critic, à corriger par Philippe dans une sous-étape ultérieure,
   3a-ter) : annuler au-delà d'un reset déjà annulé passe par des items de texte recréés (la scène
   est reconstruite par `load_image_state`, pas les objets d'origine) ; les commandes antérieures
   (`TextEditCommand`, `RestoreVersionCommand`, `TextFormatCommand`) visent l'item détruit →
   `RuntimeError` et l'annulation de la correction échoue (`app/controllers/text.py:477-479`,
   `modules/history/commands.py:61-63/:89-90`, `app/ui/commands/textformat.py:24`). Défaut
   préexistant après toute navigation (pas propre au reset), figé par
   `test_maj1_undo_past_an_undone_reset_targets_recreated_item`. Corriger ce défaut rendra aussi
   robuste le cas « changer de page puis revenir ». *(Amendement 2026-09-30 : promesse trop
   large — réglé pour le **texte** par la 3a-ter, ADR-022 ; les **boîtes tracées à la main** restent
   concernées jusqu'à la 3a-quater, critic M4.)*
2. Invalidation de cache et effacement de l'avertissement « page sautée » : non annulés par
   Cmd+Z (seul l'état de la page l'est).
3. Fidélité « navigation » plutôt que « bit à bit » : tracés Z 0,8 → 0 après reset, ordre des
   bulles qui se chevauchent peut changer.
4. Annuler écrase toute écriture faite sans passer par une commande après le reset (multi-pages,
   lot).
5. Page importée d'un PSD : l'original contient déjà le nettoyage fusionné — un reset ne peut pas
   le défaire, ce n'est pas une régression du reset lui-même.

**3a-bis, décidée par Philippe le 2026-09-28, à venir** : corriger la macro d'annulation orpheline
identifiée pendant la conception (défaut amont préexistant, indépendant du reset) : la macro
« inpaint » (`manual_workflow.py:605`) n'est fermée qu'au succès (`pipeline/inpainting.py:815`),
idem pour la segmentation ; `endMacro` vise `activeStack()` **à la fin** de l'opération, donc une
autre page si l'utilisateur a navigué entre-temps → toute commande suivante sur cette pile tombe
dans une macro jamais fermée et Annuler est refusé jusqu'à la fermeture de l'app.

**Chaîne de conception** : architect → critic pass 1 (« Architect must revise » : B1 câblage des
signaux sur les items trop tôt, B2 macro évaluée à l'index 0, M1-M9) → décisions de Philippe →
architect v2 (option C améliorée) → critic pass 2 (« Acceptable to proceed », MAJ1 accepté comme
limite connue) → décision de Philippe (accepter, corriger MAJ1 dans une sous-étape ultérieure) →
implementer → tester (OK, 7 tests ajoutés) → validation manuelle de Philippe le 2026-09-28.

**Amendement 2026-09-30** : limite MAJ1 corrigée par ADR-022 (3a-ter). Le test figé est inversé :
`test_maj1_undo_past_an_undone_reset_restores_text_on_recreated_item`.

## ADR-021 — Macros d'annulation : ouvertes au résultat, jamais au clic (`undo_guard`)

Date : 2026-09-28
Statut : Adoptée (jalon 3 de la spec 04, sous-étape 3a-bis, validée à la main par Philippe le
2026-09-28)

**Contexte** : défaut amont identifié pendant la conception de 3a (ADR-020), corrigé séparément.
Nettoyage page seule (`beginMacro("inpaint")` au clic, `manual_workflow.py:~605`, fermé seulement
au succès `pipeline/inpainting.py:~815`) et segmentation (page seule `:~705` → `:~752` succès
seulement ; multi-pages `:~644` → `:~687`/`:~691`) ouvraient une macro sur `activeStack()` au clic
et la fermaient sur `activeStack()` en fin d'opération. Erreur, Annuler pendant le calcul, file
vidée, exception dans le rappel, ou changement de page entre le clic et la fin → macro orpheline
(`canUndo()` faux, Annuler refusé sur la page) ou fermeture sur la mauvaise pile
(« endMacro(): no matching beginMacro() »). Découvert en plus pendant la conception : **changer de
page pendant un nettoyage ou une segmentation page seule** faisait poser sur B le résultat calculé
sur A (patchs de A sur la pile de B, avec le chemin de fichier de B, `image.py:1324-1326`, traits
de B effacés) — défaut amont non listé jusqu'ici.

**Options considérées** :
- **A (rejetée)** : correction ponctuelle à chaque site d'ouverture/fermeture de macro. Ne couvre
  pas le cas « file vidée avant que le rappel de succès ne s'exécute » (étape fantôme, macro jamais
  fermée).
- **B (rejetée)** : utilitaire qui ouvre la macro au clic et garantit sa fermeture (context manager
  ou décorateur). Même lacune que A sur la file vidée — l'ouverture au clic reste le problème de
  fond, pas seulement l'appariement ouverture/fermeture.
- **C (rejetée)** : filet global qui ferme toute macro ouverte dès que plus rien ne tourne. Jugée
  dangereuse : la double planification de `_process_next_operation` après une erreur (voir
  `task_runner.py:71-79`, limite 5 ci-dessous) aurait pu faire fermer prématurément la macro
  `render_text` d'une opération réellement en cours.
- **D (retenue)** : ne jamais ouvrir de macro au clic. La macro est ouverte **dans le rappel de
  succès**, de façon synchrone, et fermée dans le même appel (`try/finally`) — plus aucune macro
  ouverte d'un tour de boucle d'événements à l'autre pour le nettoyage et la segmentation. Critic :
  « Acceptable to proceed ».

**Décision** — `modules/undo_guard/` (nouveau paquet) :
- `macro.py` (pur, aucun import PySide6) : `in_macro(main, name, fn)` — pile active **au moment de
  l'appel**, ouvre/exécute/ferme dans le même appel synchrone ; `page_bound(main, name, fn,
  notify)` — capture la page affichée et sa pile **au clic**, n'exécute le rappel que si la page
  affichée et sa pile n'ont pas changé au moment du succès, sinon abandonne et prévient
  l'utilisateur (jamais de push silencieux sur la mauvaise page).
- `ui.py` (seul fichier du paquet à importer PySide6) : verrou d'annulation, `guard_cleaning`,
  `guard_segmentation`, `install_undo_guard(main)`.

**Décisions de Philippe** :
1. Changement de page pendant le calcul de nettoyage/segmentation → **résultat abandonné +
   message** (nettoyage : « Nettoyage de la page N (nom) abandonné : la page affichée a changé
   pendant le calcul. Relancez Nettoyer sur cette page. » ; segmentation : message qui précise en
   plus que les cadres effacés au lancement se rétablissent par Annuler, l'amont les effaçant déjà
   au clic).
2. **Annulation bloquée pendant le calcul** de nettoyage/segmentation : `main._undo_locked_by` posé
   au clic, levé dans le rappel de fin (appelé dans tous les cas par `GenericWorker`) ; filet par
   chien de garde à 250 ms si la file a été vidée sans rappel (`is_processing_queue` retombé à
   faux). Raccourci ⌘Z/⌘Y refusé (1 ligne `# fork:`, `shortcuts.py`). Boutons Annuler/Rétablir de la
   barre de titre : clics **avalés par un filtre d'événements** + infobulle « Indisponible pendant
   le calcul » — **jamais `setEnabled`**, voir plantage ci-dessous.

**Plantage rencontré et corrigé pendant l'implémentation** : une première version verrouillait les
boutons Annuler/Rétablir par `setEnabled(False)` sur les `MToolButton` de dayu. C'est exactement le
chemin de plantage natif de l'ADR-018 (`MToolButton.changeEvent` crée un `QGraphicsOpacityEffect`
en réponse à un autre événement en cours de dépêche, bug PySide6/Shiboken6 6.11.2). Mesuré : 4/40
plantages natifs dans ce chemin avant correction, 0/40 après passage au filtre d'événements
(2/40 résiduels, mais à la construction de fenêtres de test, sans rapport avec le verrou).

**Amont touché** : `manual_workflow.py` 19 lignes `# fork:` + 1 import (fichier édité en octets,
fins de ligne mixtes préservées : 543 CRLF / 1 CR / 210 LF, piège déjà consigné à l'ADR-016) ;
`pipeline/inpainting.py:815` (`endMacro` retiré, fermeture déplacée dans le rappel) ; `shortcuts.py`
1 ligne ; `controller.py` 2 lignes (`install_undo_guard`) ; `tests/conftest.py` 1 ligne. **Total :
24 lignes.** Branche webtoon de la segmentation non touchée (inatteignable depuis 2b, webtoon
abandonné §7 de la spec 04). Rendu (`text.py`) inchangé : il fermait déjà sa macro sur succès
**et** erreur, sur la pile mémorisée au clic — pas concerné par le défaut. `modules/reset/state.py` :
texte de confirmation de macro orpheline rendu générique (partagé avec le mécanisme du reset,
ADR-020).

**Tests** :
- `tests/test_undo_guard.py` (25, hors GUI) : `in_macro`, `page_bound` y compris changement de page
  A→B→A et cas limites, messages, garde statique sur les motifs amont **prouvée par mutation**
  (le test échoue si on réintroduit un `beginMacro`/`endMacro` couplé au clic), pureté du module.
- `tests/test_undo_guard_ui.py` (17, `--gui`) : succès/erreur/annulation/changement de page avec
  `threading.Event`/file vidée, verrou refusé par raccourci et par vrai clic puis accepté après
  levée, deux opérations enchaînées sans verrou orphelin, relâchement par nom périmé sans effet,
  segmentation page seule et multi-pages, `blk_detect_segment`, plus de confirmation « historique
  bloqué » (mécanisme du reset) après un nettoyage en échec, journal Qt capturé via `qtlog` sans
  « no matching beginMacro » ni « cannot undo in the middle of a macro ».
- Suites : 344 passed hors GUI ; `--gui` (`.venv/bin/python -m pytest`, ADR-018) 529 passed,
  3 skipped, 1 failed (`test_app.py`, échec amont connu).

**Limites connues, assumées** :
1. Le worker lit la scène **à son démarrage**, pas à la fin. S'il attend en file (ex. derrière un
   autosave) et que l'utilisateur fait A → B → A avant que le worker démarre, le résultat calculé
   sur B peut être posé sur A (annulable, mais pas empêché « par construction » — seul le
   changement de page **après** démarrage du worker est couvert).
2. Macro vide poussée au succès sans aucune écriture (parité avec le comportement amont d'origine,
   non corrigé).
3. Détecter / Reconnaître / Traduire page seule gardent le défaut « résultat posé sur la page
   affichée » (ADR-014, défauts amont n°1 et n°2) — seuls nettoyage et segmentation sont couverts
   par ce lot.
4. Nettoyage multi-pages non couvert par le verrou : ses macros par pile étaient déjà sûres
   (une pile par page, jamais partagée entre deux pages en cours de traitement).
5. Double planification de `_process_next_operation` après une erreur (`task_runner.py:71-79`,
   défaut préexistant à l'ADR-019) : `is_processing_queue` peut repasser à faux pendant qu'une
   opération tourne encore — au pire le filet à 250 ms lève le verrou un peu tôt. Consigné, non
   corrigé dans ce lot.
6. `load_segmentation_points` pousse toujours un `ClearRectsCommand` au clic (comportement amont
   inchangé).

**Pièges de test rencontrés, consignés dans `CLAUDE.md`** : une exception qui atteint
`default_error_handler` ouvre une vraie `QMessageBox.exec()` qui bloque indéfiniment la suite en
offscreen — neutraliser `Messages.show_error_with_copy` dans les fixtures concernées ; ne jamais
laisser tourner le vrai modèle (LaMa/ONNX) dans un test GUI, stubber `pipeline.inpaint` ;
`app/ui/dayu_widgets/menu.py:300` lève parfois `AttributeError ... pixelMetric` en offscreen
(bruit sans rapport, à ignorer) ; ne jamais lancer deux suites `--gui` en parallèle (partagent
l'état offscreen Qt).

**Chaîne de conception** : architect (option D) → critic (« Acceptable to proceed », M1-M4 traités
en consignes) → décisions de Philippe (verrou, abandon + message, jamais `setEnabled`) →
implementer → tester (OK, puis plantage natif dans `setEnabled` trouvé et corrigé — clics avalés,
mesure 4/40 → 0/40) → validation manuelle de Philippe le 2026-09-28.

## ADR-022 — Annulations de texte robustes aux items recréés (`text_undo`)

Date : 2026-09-30
Statut : Adoptée (spec 04 jalon 3, sous-étape 3a-ter, validée à la main par Philippe le 2026-09-30)

**Contexte** : MAJ1 de l'ADR-020. `TextEditCommand` et `TextFormatCommand` (amont) et
`RestoreVersionCommand` (fork) mémorisaient l'objet `TextBlockItem`. Après rechargement de la scène
(changement de page puis retour, reset puis annuler, rendu annulé puis rétabli), l'item était
détruit ou détaché → `RuntimeError: already deleted`, ou annulation sans effet visible alors que le
bloc changeait. Défaut préexistant après toute navigation, pas propre au reset.

**Options considérées** : A à E. **Retenue : A** — résoudre l'item cible à chaque application
(appariement sur la scène vivante) dans un paquet neuf, sans réécrire les commandes amont au-delà
d'une ou deux lignes. Critic : « Acceptable to proceed », avec conditions M1-M5.
Options rejetées :
- **B — sous-classes du fork poussées à la place** des commandes amont (`RobustTextEditCommand`,
  `RobustTextFormatCommand`) : 12 sites de construction à modifier (1 pour TE, 11 pour TF dans
  `text.py`), ou un alias d'import ; dépend de noms privés amont (`_apply`, `_get_item`) dont un
  renommage désactiverait la protection en silence ; tout nouveau site amont non protégé.
- **C — registre qui remappe ancien item → nouvel item à chaque rechargement** : 5 à 7 sites amont
  (capture avant `clear_scene`, appariement après chaque recréation), parcours de toutes les piles et
  macros, réécriture d'attributs privés des commandes ; l'appariement géométrique reste nécessaire et
  les retraits non tracés (Segmenter) ne sont pas couverts.
- **D — commandes par clé seule** (façon `ReplaceBlocksCommand`) : A sans le chemin nominal, plus de
  lignes amont et un comportement modifié même quand tout va bien.
- **E — garder les items vivants à la navigation** : option B de l'ADR-020, déjà rejetée par le
  critic (liste de blocs neuve, ordre d'empilement, rectangles hors scène).

**Décision** — `modules/text_undo/` (nouveau paquet) :
- `match.py` (pur, sans PySide6 ni shiboken6) : sélection du candidat, tolérances amont (±5 px de
  position, ±1° de rotation), vérification du texte attendu, refus en cas d'égalité, liste blanche
  `FORMAT_KEYS`, `is_valid` injecté.
- `resolve.py` (importe `shiboken6`) : `apply_text_edit`, `resolve_format_target`.
- **Chemin nominal** (item valide et dans la scène) identique à l'amont, sauf qu'un bloc mort est
  remplacé par le bloc apparié à l'item, ou `None` (critic M3 : jamais d'écriture ni de
  `curr_tblock` sur un bloc mort, ex. après un nouveau Détecter).
- **Sinon** : candidats parmi `viewer.text_items` attachés → filtres position/rotation → **texte
  attendu vérifié même avec un seul candidat** (critic M2 : jamais écraser un texte changé entre-
  temps, ex. « Tout remplacer » depuis une autre page) → contrôle croisé item↔bloc → plus proche ;
  égalité → refus. Ancre `_fork_anchor` (page, position, rotation) rafraîchie à chaque application
  réussie.
- `RestoreVersionCommand` résout à chaque application ; `_applied` inchangé si rien n'est muté.
- `TextFormatCommand` : cible parmi `scene.items()` ; `old_dict`/`new_dict` réduits une fois à
  `FORMAT_KEYS` à la substitution (jamais `layout`, `_ct_text_changed_slot`, `selected`,
  `editing_mode`, `vertical`). Le repli amont `find_matching_txt_item` est remplacé (cas couverts
  par la nouvelle résolution).

**Décisions de Philippe** :
- **D1** — l'édition de texte en attente (minuterie 400 ms) est validée **au changement de page**
  (`image_ctrl.display_image`, avant `save_current_image_state`).
- **D2** — si l'item n'existe plus : texte écrit sur le bloc vivant seul (panneau mis à jour), rien
  pour le format, jamais d'exception ni de recréation d'item, **pas de message** (journal seulement).
- **D3** — commandes de boîtes à liste orpheline traitées à part : **3a-quater** (à venir).

**Correction du critic M1 (bis)** : l'édition en attente est aussi validée **juste avant Annuler/
Rétablir** — raccourci (1 ligne `shortcuts.py`, après la ligne du verrou d'`undo_guard`, qui garde la
priorité) et boutons de la barre de titre (signal `pressed`, émis avant `clicked`, branché dans
`modules/undo_guard/ui.py` ; sous verrou, l'appui est avalé par le filtre et rien n'est validé).
Effet : taper puis ⌘Z aussitôt valide la frappe puis l'annule ; ⌘Y la rétablit — aucune perte.

**Exception à l'ADR-012** : le chemin « bloc seul » de `TextEditCommand` écrit `blk.translation` sans
`set_text`, comme le chemin nominal amont ; `flush_pending` rattrape en `manual`. Le chemin bloc seul
de `RestoreVersionCommand` passe, lui, par `set_text`. Mesuré : 15 cycles annuler/rétablir +
navigation n'ajoutent qu'une entrée `manual` à l'historique de la bulle.

**Effet de bord de D1 (critic m10)** : une édition en attente pendant une macro de rendu ouverte
entre dans cette macro (annuler le rendu l'annule aussi). `display_image` n'est jamais appelé depuis
un `redo`/`undo`.

**Amont touché** : `app/ui/commands/text_edit.py` 2 lignes `# fork:`, `textformat.py` 2 (la ligne
de `_get_item` remplace 3 lignes d'origine), `app/controllers/image.py` 1 (D1),
`app/controllers/shortcuts.py` 1, `tests/conftest.py` 1. Aucune dans `text.py`.

**Tests** : `tests/test_text_undo.py` (55, hors GUI), `tests/test_text_undo_ui.py` (~44, `--gui`,
dont 20 ajoutés par le tester sur les vrais chemins : navigation par `display_image`, raccourcis
réels, minuterie réelle de 400 ms, vrais clics et Espace sur le bouton Annuler, textes difficiles,
historique), `tests/test_reset_ui.py` (MAJ1 inversé). Sensibilité prouvée par mutation. Suites :
399 passed hors GUI ; `--gui` 627 passed, 4 skipped, 1 failed (`test_app.py`, amont connu). Une
exécution complète s'est arrêtée une fois sur un plantage natif non attribué (famille ADR-018
probable), relance verte.

**Limites connues, assumées** :
1. `TextFormatCommand` n'a pas de contrôle de page (la commande n'a pas `main`).
2. Commandes de boîtes (`AddRectangleCommand`, `DeleteBoxesCommand`, à vérifier
   `BoxesChangeCommand`/`ResizeBlocksCommand`) : liste `main.blk_list` de leur construction remplacée
   à la navigation → hors périmètre, **3a-quater** (D3). Les boîtes tracées à la main restent donc
   concernées par « changer de page puis revenir » (critic M4).
3. Le chemin « bloc seul » contourne `set_text` (exception ADR-012 ci-dessus).

**Chaîne de conception** : architect → session interrompue → critic relancé (« Acceptable to
proceed », conditions M1-M5) → décisions de Philippe D1/D2/D3 → implementer → tester (OK) →
validation manuelle de Philippe le 2026-09-30.
