# JOURNAL

## 2026-09-25 — Spec 04 jalon 1 : test manuel validé

- Premier test réel : pastilles présentes mais **invisibles sur thème sombre** (case éteinte =
  trait 1 px `palette.mid` à 35 % d'opacité, écart mesuré de 5 niveaux sur 255 sur la capture) et
  5e case en partie sous la barre de défilement superposée de macOS. Corrigé dans
  `modules/pagestate/ui.py` seul, sans ligne amont : case éteinte = même rectangle qu'une case
  pleine, couleur du texte à alpha 60 ; piste arrêtée avant la barre de défilement
  (`_scrollbar_left`). Tests inchangés : 240 passed hors GUI, 287 passed `--gui` (+ échec amont
  connu `test_app.py`).
- Traduction en échec « No route to host » pendant le test : **réglage « Réseau local » de macOS
  bloqué sur l'Air**, pas un défaut de code. Tout binaire non signé Apple (Python système et `uv`,
  Node) refusé vers tout le LAN, box comprise, Internet OK, `curl` OK ; identique depuis iTerm et
  Terminal.app, iTerm autorisé, filtre Little Snitch désactivé, Wi-Fi du Mini coupé (le Mini est
  désormais en Ethernet seul, 192.168.1.101). Résolu par redémarrage de l'Air. Note de `CLAUDE.md`
  corrigée (elle accusait Little Snitch à tort).
- Test manuel de Philippe : **pastilles fonctionnelles**.
- Reste à faire : commit du jalon B de la spec 03 puis du jalon 1 de la spec 04 ; décision sur le
  mode webtoon avant le jalon 2.

## 2026-09-22 — Spec 04 jalon 1 : état d'avancement par page

- Brief et spec 04 rédigés le 2026-09-21 (`specs/brief-refonte-interface.md`,
  `specs/04-refonte-interface.md`), à partir de la maquette « Atelier de traduction BD ». Décisions
  de Philippe sur les 5 questions ouvertes : sélection de pages plutôt qu'un mode Page/Album ;
  rendu final affiché par défaut à l'ouverture d'une page traitée ; nouvelle fenêtre principale
  plutôt qu'un réagencement de l'existante ; mode revue dédié conservé (jalon tardif) ; le lot est
  le point 1 du travail. Découverte au passage : le lot sur sélection de pages existe déjà (clic
  droit dans la liste, `controller.py:596`, rapport de lot, reprise des pages sautées) mais n'est
  annoncé nulle part dans l'interface ; les boutons radio Manuel/Automatique grisent la moitié des
  commandes selon un réglage que rien n'explique (§3 de la spec, à supprimer au jalon 2).
- Chaîne de conception du jalon 1 : architect → critic pass 1 (« Architect must revise », 1
  bloquant M1 + 3 majeurs) → arbitrage de Philippe (option A, déduction pure sans persistance) →
  conception v2 → critic pass 2 (« Acceptable to proceed », 7 mineurs) → implementer → tester (OK)
  → security-reviewer non déclenché (module `modules/pagestate/` lecture seule, aucun
  réseau/fichier/sous-processus) → doc-writer. Détail : ADR-014 (`specs/decisions.md`),
  `specs/04-refonte-interface.md` §5 jalon 1.
- Décision : deux statuts par étape (FAITE / ABSENTE), recalculés à l'affichage, **aucune donnée
  persistée, aucun point d'écriture** dans les chemins manuel/lot/cache/undo. Format `.ctpr`
  inchangé dans les deux sens. Option B (drapeau persisté « étape lancée », 3e statut VIDE) rejetée
  après revue du critic : mentait après une ré-détection, s'affichait VIDE pendant l'opération,
  divergeait selon le chemin (page seule / multi-pages / lot), pouvait viser la mauvaise page en
  cas de navigation pendant le traitement. Le signal « lancée sans résultat » est reporté au
  jalon 3 (message à la complétion d'une étape).
- Construit : `modules/pagestate/{__init__,progress,collect,ui}.py` (nouveau paquet — `progress.py`
  et `collect.py` purs, `ui.py` seul fichier à importer PySide6, délégué par composition autour du
  délégué amont de la liste de pages) ; `controller.py` 2 lignes `# fork:` (attache en fin de
  `ComicTranslate.__init__`, pas dans `workspace.py` qui s'exécute trop tôt — bloquant M1 du critic
  pass 1) ; `tests/conftest.py` 1 ligne `# fork:`. 3 lignes amont, 2 fichiers touchés, zéro ligne
  dans `list_view.py`, `image.py`, `manual_workflow.py`, `text.py`, `pipeline/*`, `app/projects/*`.
- Mesures et tests : `tests/test_pagestate.py` (27, hors GUI), `tests/test_pagestate_ui.py` (15,
  `--gui`). `uv run pytest -q` → **240 passed** ; `--gui` → **287 passed, 3 skipped**, 1 failed
  (`test_app.py`, échec amont connu). Ruff OK. Chien de garde (rattrape les écritures non
  signalées) : coût médian 0,53 ms/tick mesuré sur 242 pages × 30 blocs. Non-écriture prouvée (pas
  seulement affirmée) : octets SHA-256 d'un `.ctpr` réel identiques avant/après une rafale de
  peintures, ticks et rafraîchissements.
- Défauts amont découverts en cours de conception, non corrigés (détail ADR-014, candidats PR
  amont spec 00 §5) : (1) navigation pendant un lot écrit les blocs d'une page dans `image_states`
  d'une autre à la navigation suivante (`batch_processor.py:97`/`:450-451`) ; (2) même défaut hors
  lot sur les opérations multi-pages (`context["current_file"]` périmé) ; (3) `_batch_active` peut
  rester bloqué à `True` si un lot en file derrière un autosave est annulé avant de démarrer ;
  (4) page insérée puis traitée par lot → `KeyError` au chargement suivant (`viewer_state`
  incomplet), touchera le jalon 4.
- Reste à faire : **test manuel de Philippe** sur le jalon 1 (protocole dans la spec 04 §5, encadré
  « Livré le 2026-09-22 »), commit du jalon 1, commit du jalon B de la spec 03 (toujours non
  commité, pas encore testé à la main), démarrage du jalon 2.

## 2026-09-19 — Spec 03 jalon B : voir l'original

- Chaîne complète : architect → critic pass 1 (« Architect must revise » : Alt/Option est une
  touche de composition sur clavier Mac français — conflit avec la saisie, ex. Alt+O → œ ; voile
  « collé » si un relâchement d'Alt est manqué par l'app ; clics avalés par le mécanisme envisagé)
  → conception v2 → critic pass 2 (« Acceptable to proceed », 2 consignes bloquantes : ne jamais
  peindre le voile sans photo ni en webtoon quel que soit l'état du bouton, resynchroniser Alt sur
  l'état réel du clavier) → implementer. Détail : ADR-013 (`specs/decisions.md`),
  `specs/03-historique-et-calques.md` §9.
- Mécanisme retenu : `modules/view/original.py`, `OriginalViewImageViewer(ImageViewer)` peint le
  voile (fond opaque puis photo d'origine) dans `drawForeground` — vue, jamais scène. Mesuré :
  `scene.render()` (export image/CBZ/PDF/PSD, « enregistrer l'image courante » Cmd+E) ignore le
  voile par construction ; OCR/détection/traduction/nettoyage insensibles ; aucune levée
  temporaire nulle part. Deux déclencheurs : bouton **Original** (checkable, colonne Outils) et
  touche **Alt/Option** maintenue, armée seulement si espace de travail actif, aucune fenêtre
  modale, fenêtre principale active, aucune saisie en cours (champ éditable focalisé ou bulle en
  édition), et pas en mode webtoon ; désarmée sur relâchement, désactivation de fenêtre,
  changement d'état applicatif, et resynchronisée sur l'état réel du clavier au premier événement
  suivant. Aucun clic avalé (éléments restent cliquables sous le voile). Rien n'est persisté
  (`.ctpr`, QSettings). 5 lignes `# fork:` (`window.py` 2, `workspace.py` 2, `tests/conftest.py`
  1). Raccourci clavier configurable coupé (coût amont disproportionné pour un 3e déclencheur).
- Alternatives rejetées (détail ADR-013) : `setVisible` par item (casse « enregistrer l'image
  courante », hooks sur chaque création d'item, undo/redo, webtoon) ; vue de comparaison séparée
  (~400 lignes estimées) ; widget de recouvrement enfant du viewport (pas de signal de
  transformation fiable sur `QGraphicsView`) ; Espace comme déclencheur (tape dans les champs,
  déclenche les boutons focalisés).
- Portée : ferme le critère §6.2 de la spec 03. Laisse ouverte la visibilité par couche (voir la
  page nettoyée sans texte, par exemple) — impossible avec un voile tout-ou-rien, jalon ultérieur
  seulement si demandé.
- Tests : `tests/test_original_view.py`, 22 tests `--gui` offscreen (export et `save_state`
  identiques octet pour octet avec/sans voile, bouton/touche/auto-repeat/relâchement, changement
  de page, rendu et nettoyage pendant le voile + undo/redo, aucune clé nouvelle dans l'état,
  webtoon et absence d'image → rien peint, désarmement sur désactivation/modale, resynchronisation
  clavier, `save_current_image` bout en bout identique, Alt inhibé en saisie y compris « œ »).
  Suite complète : 213 tests hors GUI inchangés, 245 avec `--gui` + l'échec amont connu de
  `test_app.py`. Limite de test documentée : sous le pilote offscreen, le viewport de la fenêtre
  sans bordure reste à 100×30 px — les tests de pixels utilisent une vue autonome.
- Reste à faire : **test manuel de Philippe** sur `funhome_012` (protocole décrit dans la spec 03
  §9), commit de ce lot.

## 2026-09-16 — Spec 03 jalon A : versions par bloc

- Chaîne complète : architect → critic pass 1 (« Architect must revise », 5 bloquants B1-B5) →
  conception v2 → critic pass 2 (« Acceptable to proceed », 5 majeurs traités en consignes) →
  implementer → **tester en cours**. Détail : ADR-012 (`specs/decisions.md`), `specs/
  03-historique-et-calques.md` §8.
- Bloquants pass 1, tous levés en v2 : B1 un deuxième « Traduire » souvent servi par le cache sans
  rappeler le traducteur (édition entre-temps perdue si non captée à l'affectation) ; B2 l'édition
  du champ traduction réécrit `blk.translation` à chaque frappe, hors commande Qt ; B3 enregistrer
  seulement la valeur nouvelle perd toute écriture non instrumentée entre deux captures, d'où la
  règle du **pré-état** ; B4 OCR/traduction en mode bloc unique travaillent sur des copies
  jetables, le vrai point de convergence est l'**affectation** sur le bloc vivant (6 sites) ; B5
  `set_upper_case` s'applique après chaque traduction, comparaisons par `casefold`.
- Décision : module pur `modules/history/versions.py` (`set_text` point d'entrée unique, ordre
  impératif valeur courante → tête du journal du champ → pré-état → relecture → dédoublonnage →
  écriture → append), `snapshot`/`record_diff` pour les processeurs OCR/traduction (seul endroit
  où le nom du moteur est disponible), `flush_pending` dans `save_image_state` (rattrape + élague,
  fil GUI uniquement), restauration annulable via `RestoreVersionCommand` (`modules/history/
  commands.py`), bouton + menu « Historique du bloc » (`modules/history/ui.py`). Attribut
  `versions` paresseux sur `TextBlock`, sérialisé automatiquement par `__dict__`.
- Alternatives rejetées : versions indexées par identité de bloc (pas d'identifiant stable) ;
  propriétés `text`/`translation` sur `TextBlock` (casse le chargement des projets de l'app
  d'origine) ; diff aux seuls processeurs (v1, ne couvre pas B1/B2/B4) ; `app/history/` (exclu de
  ruff en bloc, ADR-008) → `modules/history/`.
- Construit : 8 fichiers amont touchés, 29 lignes `# fork:` ; `search_replace.py`, `text.py`,
  `commands/base.py`, `project_state_v2.py` non touchés.
- Défauts connus consignés dans ADR-012 : lot (`batch_processor.py:441-443`) remplace `blk_list`,
  journal perdu ; webtoon non couvert ; Rechercher/Remplacer non instrumenté (rattrapé par le
  pré-état) ; journal partagé possible après suppression/annulation d'un bloc (aliasing amont
  préexistant) ; > 2 000 caractères sans historique ; correction de casse pure non journalisée ;
  volumétrie bornée seulement après flush de la page courante ; `deep_copy` de l'app d'origine
  perd `versions` sans plantage.
- Tester : 4 fichiers de tests ajoutés (`tests/test_block_versions_handlers.py`,
  `tests/_upstream_paths.py`, `tests/_robustness.py`, `tests/test_legacy_ctpr_compat.py`), suivis
  de 2 correctifs — `set_text(None)` coercé en chaîne vide (robustesse d'appel) ; menu Historique
  affichant « Aucun historique pour ce bloc » grisé quand le bloc n'a pas de journal (au lieu d'un
  menu vide ambigu avec « Aucun bloc sélectionné »).
- Chiffres finaux : `uv run pytest -q` → **213 passés** ; `--gui` complet → **226 passés** + l'échec
  amont connu de `test_app.py` (préexistant, ADR/JOURNAL du 2026-09-12, hors périmètre). Scénario
  complet rejoué hors écran avec sauvegarde `.ctpr` et rechargement dans une seconde instance :
  journal `[translation, manual, cache, restore]` conservé, valeur restaurée en place.
- Compatibilité ascendante testée : 3 tests de `test_legacy_ctpr_compat.py` passés, ouverture d'un
  projet antérieur au jalon A via la variable d'environnement `COMIC_TRANSLATE_LEGACY_CTPR=<chemin
  d'un .ctpr créé avant le jalon>` (tests sautés si la variable est absente ; le fichier contient
  une page de BD, jamais commité — cohérent avec l'interdit « aucune page de BD dans git »). La
  contre-épreuve « projet antérieur » de la spec 03 §8 est désormais automatisée par ce test, en
  plus du protocole manuel.
- Reste à faire : **test manuel de Philippe** sur `funhome_012` (protocole décrit dans la spec 03
  §8), commit de ce lot.

## 2026-09-15 — Hotfix détection : fausses bulles sur les légendes

- Symptôme rapporté par Philippe (capture du 2026-09-15, page 11 de l'album de test) : le masque
  de segmentation d'une légende narrative de 3 lignes avait la forme d'une ellipse qui coupait le
  début de la première ligne et la fin de la dernière ; les autres légendes et les bulles étaient
  correctes.
- Diagnostic : RT-DETR émet une boîte de « bulle » calée exactement sur la légende (bulle
  `[31,609,797,682]`, texte `[30,610,797,681]`) → `create_text_blocks`
  (`modules/detection/base.py`) classe le bloc `text_bubble` → `clip_mask_components_to_bubble` ne
  trouve pas de contour de bulle fermé et retombe sur l'ellipse inscrite (`build_bubble_clip_mask`),
  qui tronque les coins. Mesure sur les 242 pages de l'album (1 388 blocs classés bulle) : les
  fausses bulles ont une marge minimale boîte de bulle/boîte de texte de 0 à 1 px (374/390 blocs
  sous 2 px — 28 % de tous les blocs « bulle ») ; les vraies bulles ont une marge ≥ 4 px et un
  rapport d'aire ≥ 1,18 (médiane 1,69, marge médiane 10 px). Distribution bimodale, aucun bloc
  entre 2 et 4 px hors 16 cas à rapport 1,33.
- Correctif (détail ADR-011, `specs/decisions.md`) : `MIN_BUBBLE_MARGIN_PX = 3` sur
  `DetectionEngine`, appariement bulle/texte rejeté sous ce seuil (le bloc redevient `text_free`
  s'il n'y a pas d'autre bulle candidate) ; 16 lignes `# fork:` dans `modules/detection/base.py`,
  seul point d'appariement (webtoon et lot passent par le même code).
- Vérification : banc 9 pages, blocs bulle 40 → 38 (`funhome_011` et `funhome_020` basculent un
  bloc chacune) ; planche `funhome_011` en mode manuel : masque complet sur les 3 lignes, nettoyage
  sans coin coupé. Tests : `tests/test_detection_bubble_margin.py` (5 tests synthétiques, sans
  modèle) ; suite complète 168 passés.
- Effet induit sur le nettoyage (spec 02) : les légendes reclassées passent par le chemin légende
  (aplat + protection des cadres) au lieu du chemin bulle, et ne créent plus de fausses zones de
  bulle qui bloquaient le remplissage des voisines — banc à relancer sur les 9 pages avec les
  nouveaux blocs avant toute nouvelle calibration (spec 02 §12).
- Banc relancé le jour même sur les 9 pages avec les blocs regénérés par le détecteur corrigé
  (`bench/out/blocks_v3`, spec 02 §12 bis) : couverture stable ou en hausse sur les pages
  affectées (011 0 %→17 %/17 %, 020 0 %→33 %/33 %, 100 et 120 en légère hausse), page 011 (légende
  du bas reclassée) désormais nettoyée sans coin coupé. Coût mesuré : +0,3 à +2 s/page (détection
  par composantes + clips de bulle), ce n'est plus « non supérieur » comme au jalon 1. `sans_bloc`
  en mode manuel reste élevé (9 à 26 fragments/page), sans défaut visuel rapporté — piste ouverte.
- Candidat PR amont (spec 00 §5) : ce filtre de marge est générique, indépendant du fork Ollama.
- Incidents d'environnement du 2026-09-14/15, consignés au passage : (1) Little Snitch bloquait le
  Python de `uv` (`~/.local/share/uv/python/…/bin/python3.12`) vers tout le réseau local
  (« No route to host » vers l'endpoint Ollama du Mini), alors que `curl` et le Python système
  passaient sans problème ; réglé par la mise à jour macOS 27 puis redémarrage — règle à surveiller
  si ça revient (« Allow python3.12 → réseau local 11434 ») ; (2) coupure réseau passagère vers le
  Mini, sans rapport avec le hotfix. Ligne ajoutée à `CLAUDE.md` (« Défauts amont connus »).

## 2026-09-13 — Spec 03 : inventaire de l'existant

- Livrable : `specs/03-inventaire.md` (architect, lecture seule, aucune ligne de code). Périmètre :
  le tableau du §2 de `specs/03-historique-et-calques.md`, complété par une mesure §8.
- Constats clés : le `.ctpr` est une base SQLite (et non une archive ZIP) ; elle conserve les
  blocs (`blk_list` complet), le texte source OCR, la traduction courante, les patchs de
  nettoyage, les tracés de pinceau et les langues par page. L'historique d'images est du **code
  mort** : une seule entrée par page en pratique, le signal `image_processed` qui alimenterait une
  deuxième entrée n'est **jamais émis** dans le dépôt. Aucune couche n'est masquable dans le
  viewer, donc pas de « voir l'original ». Aucune version de traduction : `TextBlock.translation`
  est un champ scalaire unique, écrasé par 7 chemins (LLM, cache, mise en casse, édition manuelle,
  Rechercher/Remplacer, lot). La pile Annuler/Rétablir n'est **pas persistée** : recréée vide à
  chaque chargement de projet ou d'images. OCR, traduction et traitement par lot ne sont **pas
  annulables** (seule la détection page seule l'est). Les patchs de nettoyage sont **empilés**,
  jamais remplacés, même sur la même zone. L'export PSD conserve le rendu (image + texte éditable)
  mais pas l'état de travail (blocs, texte source, traductions, patchs séparés). `meta.
  project_format_version` est écrit mais **jamais lu** ; les clés/tables inconnues sont ignorées à
  la lecture (`.get(...)`), sauf `strict_map_key=True` (clés de dict non str/bytes → échec) et les
  types non encodables par `ProjectEncoder` (`TypeError` à l'enregistrement).
- Mesure 8.1 (aller-retour `.ctpr` hors écran, page `funhome_012`, mode manuel) : blocs, texte
  source, traduction courante, patchs, tracés et langues conservés à l'identique ; poids 728 Ko
  pour une page (362 Ko image + 247 Ko de 6 patchs) ; **`v1` de traduction perdue** au profit de
  `v2` (confirme §1.3) ; **pile d'annulation perdue** (groupe vide après réouverture, confirme
  §1.4) ; historique d'images toujours à une seule entrée (confirme §3).
- Verdict sur les hypothèses de la spec : **E1 (calques + « voir l'original ») absent** ; **E2
  (journal de page persisté) quasi absent**, seul le rapport de lot est sauvé (pages sautées
  uniquement) ; **E3 (versions de traduction) absent** ; **E4 (découvrabilité) partiellement
  couvert**, le socle existe mais est peu visible (champs vidés au changement de page, aucune
  étiquette, sauvegarde auto désactivée par défaut).
- Arbitrage attendu de Philippe : liste E1-E4 retenue et ordre de priorité, après lecture de
  l'inventaire.
- Reste à mesurer : §7.2 (lot/webtoon), §7.3 (nettoyage répété, taille fichier), §7.4 (retraduction,
  partiellement fait), §7.5 (album complet), §7.6 (clés inconnues, fichier d'origine), §7.7 (PSD),
  §7.8 (découvrabilité chronométrée), §7.9 (piles entre pages).
- Toujours non commitées à cette date : specs 01 et 02 (jalons 1 et 2) et le hotfix OCR locale
  fr_FR/onnxruntime.

## 2026-09-13 — Spec 02 jalon 2 : calibration sur la page de Philippe

- Chaîne complète : architect → critic (2 passages) → implementer → tester. Critic pass 1 :
  2 bloquants (B1 zone de non-peinture des bulles fondée sur une bbox +7 au lieu du contour réel ;
  B2 aucune mesure faite avant de coder) + 9 constats sérieurs (M1-M9, dont le garde-fou bbox
  texte à conserver malgré son coût, la restriction du retrait N2 aux bandes ∩ ¬zone bulle, et
  `bubble_overlap_max` resserré à 0,20 par mesure). Critic pass 2 (verdict « Acceptable to
  proceed ») : 4 nouveaux bloquants levés par 12 consignes impératives (résolution
  multi-propriétaires avant `partagee`, contour de bulle couvrant l'encre par construction,
  sémantique stricte `core \ core_fill`, fondu bloqué sur le contour, plafond de saturation sans
  repli vers `runs`, retrait de l'anneau-barrière/fusion/proximité faute d'effet mesuré, clip de
  bulle calculé une fois, colonnes CSV de diagnostic). Toutes appliquées.
- Diagnostic sur la capture réelle de Philippe (`funhome_012`, mode manuel Detect → Segment →
  Clean) : 3 traînées grises sous les légendes narratives, bord supérieur des cases rongé, bulles
  propres. Cause détaillée dans `specs/02-nettoyage-legendes.md` §12 et ADR-010
  (`specs/decisions.md`) : bulles collées au bord d'une case (chevauchement mesuré 15,6 %/7,4 %),
  légende à cadre à la main ondulé non détectée par l'ancien `run_ge`, 11 composantes `sans_bloc`
  en manuel.
- Construit : contour réel de bulle exclu par construction (`build_bubble_clip_mask` + dilatation
  calibrée), détection des traits fins par composantes connexes (traits non-axiaux, cadre ondulé
  compris), résolution des co-propriétaires bulle/légende, `mask_entry`/`core_ratio` figés
  indépendamment de l'ordre des labels, colonnes CSV de diagnostic (`aire_core`, `bbox_core`,
  `distance_bloc_le_plus_proche`, `clip_bulle`, `n_ring_geom`, purges ventilées). Mécanismes
  mesurés puis retirés : anneau-barrière, fusion des fragments par bloc, attribution par
  proximité.
- Mesures : prototypes avant conception (détection encre fine sur page entière → 229 501 px
  protégés, 20 % de la page, restreint aux bandes text_free → 17,5 %) ; `core_ratio` sur l'anneau
  géométrique avant purge (0,80 au lieu de 0,89-0,92 après purge, décisif pour les légendes
  collées à une bulle) ; anneau-barrière sans effet mesuré (`n_ring` 6 048 → 5 777).
- Résultats banc (mêmes blocs figés, avant → après) : page 012 (page de Philippe) lot 40 % → 100 %,
  manuel 40 % → 100 %. Autres pages : 020 stable à 0 %, 045 lot stable à 80 % (mixtes 1 → 2)/manuel
  stable à 20 %, 060 stable à 0 %, 080 lot 40 % → 30 % (mixtes 2 → 1)/manuel 0 % → 10 %, 100 stable
  à 50/75 %, 120 lot stable à 67 %/manuel 33 % → 67 %. Temps ≈ inchangés (3,6-4,3 s/page CPU, LaMa
  dominant). Sweep `bubble_overlap_max` (0,10/0,20/1,0) : 44,1/45,7/44,4 % uni global (6 pages) ;
  `line_detector` components 45,7 % vs runs 40,0 %.
- Tests : 162 passés + 1 xfail au moment de la rédaction (163 attendus après un correctif d'une
  ligne en parallèle) ; nouveau `tests/test_cleaning_e2e_legende.py` (cadre ondulé + légende +
  bulle collée + lavis) et 7 tests supplémentaires exigés par le critic pass 2 (co-propriété,
  contour/intérieur de bulle en égalité stricte, `core \ core_fill` masqué, saturation, M2 figé,
  M3 réécrit, miettes, ordre des labels).
- Bug amont trouvé en cours de mesure : `imkit/transforms.py:425-426` surestime largeur/hauteur
  des composantes de 1 px (bornes mahotas déjà exclusives) ; compensé dans
  `modules/cleaning/uniform.py`, `imkit` non modifié (candidat PR amont, spec 00 §5).
- Reste à faire : **retour visuel de Philippe** sur la page de référence (protocole de test
  manuel décrit dans la spec, cases cochées puis contre-épreuve décochées) ; décision sur la
  légende à cadre ondulé (0,93 uni, prédite `lama` par la conception, mais visuellement propre sur
  la planche) ; commit des specs 01/02 et de ce lot (toujours non commités à cette date) ;
  résorption des 11 `sans_bloc` (piste non close, mécanismes candidats mesurés et retirés) ;
  démarrage spec 03.

## 2026-09-13 — Hotfix OCR : locale fr_FR et onnxruntime

- Symptôme rapporté par Philippe : « Reconnaître » mouline une demi-seconde, journal `OCR
  completed and cached for N blocks`, mais tous les textes vides, champ source vide.
- Diagnostic en 3 étapes : (1) moteur PP-OCR seul (script hors Qt) → OK, reconnaît correctement ;
  (2) même modèle appelé depuis l'app → KO, sortie constante (blanc) quelle que soit l'image ; (3)
  bissection Qt/import/locale : reproduit sans Qt par `locale.setlocale(LC_ALL, "fr_FR.UTF-8")`
  avant `import onnxruntime` (`en_PP-OCRv5_rec_mobile_infer.onnx`, argmax = blanc, indépendant de
  l'entrée) ; non reproduit en locale `C`, ni si onnxruntime est importé avant Qt. Cause : Qt
  (`QApplication`) applique la locale système (`LC_NUMERIC=fr_FR.UTF-8`, virgule décimale), puis
  onnxruntime 1.30 (CPU, macOS arm64) est importé plus tard (imports paresseux des moteurs) et
  mésinterprète des flottants du runtime. LaMa et le détecteur RT-DETR non affectés (sorties
  identiques au bit près sous les deux locales).
- Correctif : `locale.setlocale(locale.LC_NUMERIC, "C")` juste après la création de `QApplication`
  dans `comic.py` (2 lignes `# fork:`). Contournement sans correctif : `LC_ALL=C uv run comic.py`.
- Vérification : app hors écran (offscreen), 10/10 blocs lus sur une page, champ source rempli.
- Défauts de découvrabilité relevés au passage (spec 03, E4) : « Reconnaître » sort en silence
  s'il n'y a aucun rectangle sur la page (`pipeline/ocr_handler.py:24`, aucun message) ; le
  résultat OCR n'est visible que dans le champ source après sélection d'un bloc. Langue source
  « Auto » colle les lignes sans espaces (« WHEN WESPOTTED ONE,SHE… ») là où « English » donne un
  texte propre.
- Invisible en amont (développeurs en locale anglaise) : candidat PR amont prioritaire
  (spec 00 §5).
- Tests : `tests/test_locale_onnxruntime.py` en cours d'écriture (non-régression).

## 2026-09-13 — Spec 02 : nettoyage des légendes

- Chaîne complète : architect → critic (2 passages) → implementer → tester → security-reviewer →
  doc-writer. Passage 1 du critic : bloquants sur le marqueur de texte du banc (B1), la géométrie
  d'attribution des composantes (B2), l'ordre N2 → bulles → N1 (B3) et le contrat de non-écriture
  de `clean_page` (B4) — tous levés en conception v2. Passage 2 (verdict « Acceptable to
  proceed ») : 10 consignes impératives données à l'implementer, notamment exposer `human_mask`
  dans `_generate_mask_from_saved_strokes` (page seule vs sélection multi-pages), exclure aussi
  les bulles dilatées de l'anneau N1 (`bubble_ring_exclusion`), chiffrer un critère de couverture
  avec ventilation des skips et détection des blocs mixtes, et fiabiliser `run_ge` (convention de
  décalage, équivalence prouvée seulement pour `L` impair). Toutes appliquées.
- Incident et réparation : le hook global `PostToolUse` (`ruff format` après chaque `Edit`/`Write`)
  a reformaté 9 fichiers d'origine en intégralité (1 594 lignes) au lieu des 748 lignes réellement
  concernées par le fork. Réparé par restauration puis réapplication manuelle des seuls hunks
  `# fork:` (243/33 lignes). Correctif : `[tool.ruff] force-exclude = true` + `extend-exclude`
  explicite des dossiers d'origine dans `pyproject.toml` (ADR-008). `modules/cleaning/` et
  `tools/` restent lintés/formatés.
- Construit : `modules/cleaning/{config,lines,uniform,apply}.py` (N2 protection des traits, N1
  remplissage uni par composantes connexes attribuées par graine, orchestration `clean_page`,
  contrat de non-écriture) ; branché en un point unique dans `pipeline/inpainting.py`
  (`inpaint_image`) avec `bubble_cleanup` injecté (jamais importé par `modules/cleaning`) ;
  réglages UI dans `app/ui/settings/tools_page.py` / `settings_ui.py` / `settings_page.py` ;
  `tools/bench_cleaning.py` (+ `tools/_common.py`) réutilisant le vrai code de nettoyage/inpainting.
- Tests : 139 passés (`uv run pytest -q`), dont 7 fichiers dédiés au nettoyage (components 6,
  uniform 8, lines 10, contract 5, invariant 3, config 8) et le banc (13) ;
  `test_manual_mask_equivalence.py` (1, `--gui` uniquement) prouve l'équivalence du masque manuel
  simulé par le banc avec le vrai chemin Qt (DrawingManager/ImageViewer, offscreen).
- Banc (7 pages « Fun Home », `bench/pages/`) : temps de nettoyage ≤ existant à ±5 % (7–8 s/page
  CPU, dominé par LaMa). Couverture très variable selon la page (0 % à 80 % de composantes
  `text_free` traitées en `uni`, ventilation des skips consignée dans la spec 02 §9.2). Écart de
  masque manuel approximé vs vrai chemin Qt : 37 % avant correction du sens de bouchage des
  contreformes (`fill_poly`) → 5,6 % après ; le mode `qt` du banc rejoue le vrai chemin (écart nul
  par construction, sert de référence).
- Sécurité : verdict OK to proceed, 2 constats majeurs corrigés avant merge (détail dans la revue
  security-reviewer, non reproduit ici). Aucun constat mineur reporté noté à ce stade.
- Reste à faire : **revue visuelle des planches par Philippe** (`bench/out/*_planche.png`) —
  critère de réussite §9.1 non validé ; **choix du jeu de paramètres final** (le sweep par axe ne
  tranche pas entre le taux d'uniforme maximal, `free_dilate_iterations=1`, et le mixte minimal
  par axe, `ring_outer=6`/`color_tolerance=16`/`uniform_share=0.75`) ; **seuil de suffisance de
  couverture** à fixer après cette revue ; piste `sans_bloc` (composantes fragmentées ne touchant
  la graine d'aucun bloc en mode manuel, cause non creusée) ; **specs 01 et 02 non commitées** au
  dépôt à cette date.

## 2026-09-12 — Spec 01 : socle du fork

- Chaîne complète : architect → critic → implementer → tester → security-reviewer → doc-writer,
  tous validés.
- Construit : socle de dépendances (`requirements.txt` source unique, `pyproject.toml` généré par
  `tools/sync_deps.py`, `uv.lock`/`.python-version` versionnés) ; F1 contexte SSL de repli
  (`modules/utils/ssl_context.py`) branché dans `download_file.py` ; F2 traducteur Custom adapté à
  Ollama (`modules/translation/llm/compat.py` + réglages UI dans la page Credentials : réflexion
  désactivée, `max_tokens`, timeout) ; F3 banc de traduction (`tools/bench_translation.py` +
  `tools/bench_cases.py`) réutilisant le vrai code de l'app (prompt, parsing JSON).
- Mesures Ollama 0.34.0 (Mini) : `translategemma:12b` (gemma3, pas de `thinking`) accepte
  `reasoning_effort: none` sans dégradation, JSON valide en ~10 s. `gemma4:12b-mlx` sans réglage
  consomme son budget de tokens dans la réflexion et rend un `content` vide (panne d'origine
  reproduite) ; avec `reasoning_effort: none`, JSON complet en 6,5 s. `max_completion_tokens` est
  ignoré par Ollama sur `/v1` (191 tokens générés au lieu de la limite), `max_tokens` est honoré.
- SSL depuis les sources : pas de reproduction de l'erreur `CERTIFICATE_VERIFY_FAILED` constatée
  sur le DMG (magasin système présent). F1 reste implémentée (robustesse, contribution amont
  possible) mais en priorité basse — ne corrige pas la panne du DMG, cause non diagnostiquée.
- Banc (vrai chemin de code, via le Mini) : `translategemma:12b` 6/6 OK (6,4–7,2 s, page 8 bulles
  13,7 s). `gemma4:12b-mlx` réflexion désactivée 6/6 OK (2,4–8,3 s, page 8 bulles 5,8 s). Incident
  pendant la session : le runner Ollama de `translategemma:12b` a renvoyé des réponses vides
  (`done: false`) ~20 min avant de récupérer seul (rechargement du modèle) — premier passage 1/6
  pour cette raison, pas un défaut de code.
- Tests : `uv run pytest -q` → 86 passed (~16 s). `--gui` : `test_app.py` échoue déjà au commit de
  base (titre de fenêtre `Comic Translate[*]`), hors périmètre de ce lot.
- Sécurité (banc) : verdict OK to proceed. Corrigés avant merge : clé API par variable
  d'environnement plutôt qu'argument en clair, neutralisation des formules CSV, `.ruff_cache/`
  ignoré. Reportés (mineurs, voir specs/01 « Défauts connus hors périmètre ») : HTTP clair + Bearer
  si `--url` distant, écrasement silencieux de `--csv`, valeurs non-str du JSON LLM, chemin d'accès
  local visible si le dépôt devient public.
- Reste à faire : fuite d'identifiants QSettings (ADR-005, reportée), `test_app.py` (reporté),
  lecture de widgets Qt hors thread GUI (non traitée dans ce lot), décision sur `main.py` orphelin
  (laissé en place, à confirmer par Philippe).
