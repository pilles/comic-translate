# CLAUDE.md — comic-translate (fork)

Fork personnel de `filvyb/comic-translate` (base `059046d`), lui-même fork de
`ogkalu2/comic-translate` (officiel, compte obligatoire — remote `upstream`,
correctifs au cas par cas seulement, pas de merge global). Remote `origin` =
`pilles/comic-translate`. Licence Apache-2.0 : conserver `LICENSE` et les
mentions d'origine. Usage strictement personnel, macOS Apple Silicon,
Python 3.12, `uv`. Voir `specs/00-feuille-de-route.md` pour le cadrage complet
et les contraintes non négociables (§6).

## Commandes

```bash
uv sync                                                    # installe l'environnement
uv run comic.py                                            # lance l'app (GUI)
COMIC_SHELL=0 uv run comic.py                               # ancienne disposition (diagnostic, ADR-015)
uv run pytest                                               # tests hors GUI (défaut)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --gui  # tests GUI ; pas `uv run` : plantage
                                                             # natif PySide6 intermittent (ADR-018)
uv run python tools/sync_deps.py --check                    # vérifie pyproject.toml vs requirements.txt
uv run python tools/bench_translation.py --model translategemma:12b
uv run python tools/bench_cleaning.py bench/pages --save-blocks bench/out/blocks --out bench/out
uv run python tools/bench_cleaning.py bench/pages --blocks bench/out/blocks --out bench/out --manual-mask
```

## Dépendances : `requirements.txt` est la source de vérité

`requirements.txt` reste la référence (facilite les rebase sur `filvyb`/`upstream`,
qui ne connaissent que ce fichier). `pyproject.toml` est **généré** — bloc
`[project].dependencies` entre marqueurs `# --- sync_deps: begin/end ---`,
régénéré par `uv run python tools/sync_deps.py --write`. Ne jamais éditer ce
bloc à la main ; éditer `requirements.txt` puis lancer `--write`. `uv.lock` et
`.python-version` sont versionnés (ADR-002).

## Règle `# fork:`

Toute ligne modifiée dans un fichier d'origine (pas les fichiers nouveaux) porte un commentaire
`# fork:`. Inventaire : `grep -rn "# fork:"`.

## Carte des modules

- `modules/translation/llm/` — traducteurs LLM (GPT, Custom, etc.) ; `compat.py`
  (nouveau) adapte les requêtes OpenAI-compatibles pour Ollama.
- `modules/utils/ssl_context.py` (nouveau) — contexte SSL de repli pour les
  téléchargements de modèles.
- `modules/utils/download_file.py` — téléchargement des modèles (détection, OCR).
- `modules/utils/translator_utils.py` — construction du prompt, parsing JSON
  de la réponse LLM (`set_texts_from_json`), casse des traductions.
- `app/ui/settings/` — pages de réglages (Credentials, dont le traducteur Custom).
- `app/projects/`, `app/controllers/projects.py` — projets `.ctpr` (sauvegarde,
  auto-save, undo/redo Qt).
- `tools/bench_translation.py`, `tools/bench_cases.py` — banc de traduction,
  utilise le vrai code de l'app (pas de duplication de prompt/parsing).
- `tools/sync_deps.py` — synchronisation `requirements.txt` → `pyproject.toml`.
- `modules/cleaning/config.py` — `CleaningConfig` (frozen), `INERT`/`UI_DEFAULTS`,
  `cleaning_config_from_settings_page` (Réglages > Outils n'expose que 3 champs :
  `uniform_fill`, `protect_lines`, `free_dilate_iterations` ; tout le reste,
  ex. `bubble_overlap_max`/`line_detector`/`bubble_interior_dilation`, reste au
  défaut du dataclass, calibré par `--sweep` — ne pas exposer sans demander,
  ADR-010).
- `modules/cleaning/uniform.py` — N1, remplissage uni par composantes connexes
  attribuées par graine (`text_free`), critère médiane + part + quadrants.
- `modules/cleaning/lines.py` — N2, protection des traits fins (bords de case) :
  `line_detector="components"` (défaut, jalon 2, `detect_line_components`,
  composantes connexes par crop de bande, traits non-axiaux) ou `"runs"`
  (`run_ge`, ancien, O(N), conservé pour mesure comparée, non exposé UI).
- `modules/cleaning/apply.py` — `clean_page` : N2 → bulles (`bubble_cleanup`
  injecté, jamais importé) → N1 ; contrat de non-écriture.
- `tools/bench_cleaning.py` (+ `tools/_common.py`) — banc visuel + CSV du
  nettoyage, réutilise `modules/cleaning` et le vrai LaMa.
- `modules/detection/base.py` — `create_text_blocks` (appariement bulle/texte, seul point commun
  lot/webtoon) : `MIN_BUBBLE_MARGIN_PX = 3` rejette l'appariement sous 3 px de marge boîte-bulle/
  boîte-texte (fausses bulles RT-DETR sur légendes, ADR-011).
- `modules/history/` — versions par bloc (spec 03 jalon A) : `versions.py` (pur, `set_text`
  point d'entrée unique — toute écriture de `blk.text`/`blk.translation` sur un bloc vivant y
  passe, jamais de `setattr` direct ; `prune` seulement depuis `flush_pending`, fil GUI),
  `commands.py` (`RestoreVersionCommand`), `ui.py` (bouton/menu, seul fichier du paquet à importer
  PySide6, depuis `workspace.py` uniquement). Détail : ADR-012.
- `modules/view/original.py` — voile « voir l'original » (spec 03 jalon B) : `OriginalViewImageViewer`
  peint la photo d'origine dans `drawForeground` (vue), jamais dans la scène ; bouton + touche Alt
  maintenue. Importé uniquement depuis `window.py` et `workspace.py`. Détail : ADR-013.
- `modules/pagestate/` — état d'avancement par page (spec 04 jalon 1) : `progress.py`/`collect.py`
  purs (déduction pure sur `blk_list`/`image_states`, **aucune écriture, jamais d'ajout d'écriture
  dans ce paquet**), `ui.py` (délégué par composition, seul fichier à importer PySide6). Importé
  uniquement depuis `controller.py`. Détail : ADR-014.
- `modules/shell/` — nouvelle disposition (spec 04 jalon 2, sous-étapes 2a/2b/2b-bis/2c, **jalon 2
  clos** le 2026-09-28) : reparente les mêmes objets construits par `_create_main_content` (jamais
  recréés — ~400 lectures de widgets par nom dans les contrôleurs) dans une disposition à 3
  colonnes. `manifest.py` (pur, noms d'attributs par zone) **seul fichier à revoir au rebase
  amont** ; zone `PARKED` (2b) — `manual_radio`/`automatic_radio`/`webtoon_toggle` — jamais
  déplacée, masquée sur place (`_hide_parked_widgets`), y compris en repli et sous `COMIC_SHELL=0`
  (webtoon seulement). Importé uniquement depuis `window.py`, n'importe jamais
  `app.controllers`/`app.ui.main_window`. Repli visible si le reparentage échoue
  (`main._shell_active = False`) ; interrupteur `COMIC_SHELL=0` pour l'ancienne disposition sans
  bandeau. `panel.py` (2c) : panneau de droite en `QStackedWidget` Page/Bulle (« Rendu du texte »/
  « Outils » communs sous la pile). `context.py` (pur, 2c) : `panel_context` décide Page vs Bulle.
  `watcher.py` (nouveau, 2c, importe PySide6) : `_ContextWatcher` bascule la pile sur signaux
  regroupés par `singleShot(0)` + chien de garde 200 ms ; règle de focus **avant tout
  `setCurrentIndex`** : lire `window().focusWidget()` (jamais `QApplication.focusWidget()`, `None`
  hors fenêtre active), rendre le focus au viewer en sortant d'une section, ne jamais en donner à la
  section entrante. Détail : ADR-015.
- `modules/reset/` — bouton « Réinitialiser » la page (spec 04 jalon 3, sous-étape 3a) : option C
  améliorée — `commands.py::ResetPageCommand` réécrit les clés traitées d'`image_states[p]`/
  `image_patches[p]` puis recharge par `image_ctrl.load_image_state(p)` (pas de détachement/
  rattachement d'items Qt vivants, écarté par le critic). Garde par **identité de pile**
  (`QUndoStack`) : une pile orpheline après rechargement de projet ne mute rien. **Jamais** de
  `push`/`beginMacro`/`endMacro`/`mark_project_dirty` dans `redo`/`undo`. `state.py` pur ;
  `ui.py` seul fichier du paquet à importer PySide6, importé **uniquement** depuis `controller.py`.
  Détail : ADR-020.

## Traduction locale (Ollama)

Traducteur **Custom**, endpoint Ollama Mini `http://daaminim4.local:11434/v1`, pas de relais HTTP
(spec 00 §3). Modèles retenus : `translategemma:12b` ou `gemma4:12b-mlx` (réflexion désactivée).
Réglages persistés (QSettings, groupe `custom_llm`) : réflexion désactivée, `max_tokens`,
timeout 180 s (10–1800).

## Ruff : ne jamais formater les fichiers amont

`[tool.ruff]` protège les fichiers d'origine du formatage auto (hook `PostToolUse` sur
`Edit`/`Write`) via `force-exclude = true` + `extend-exclude` explicite (ADR-008). **Ne jamais
retirer `force-exclude`** ; ajouter tout nouveau dossier amont touché par `# fork:` à
`extend-exclude` avant la première édition. `modules/cleaning/` et `tools/` restent lintés.

**Piège du hook `ruff --fix`** (rencontré spec 04, sous-étape 2c) : sur un fichier linté, le hook
supprime un import ajouté dans une édition s'il n'est utilisé que dans une édition *suivante*
(import jugé inutile au moment où il est posé seul). Toujours ajouter l'import et son premier usage
dans la **même** édition ; vérifier après coup par `grep -n "^import\|^from" <fichier>`.

## Règle « voir l'original »

Aucun voile ni masquage ne doit vivre dans la scène (`QGraphicsScene`/items) : tout ce qui lit la
scène (export image/CBZ/PDF/PSD, « enregistrer l'image courante », OCR, détection, traduction,
nettoyage) doit rester insensible à l'affichage. Le voile « voir l'original » (`modules/view/
original.py`) est peint uniquement par la vue (`drawForeground`), jamais par une modification
d'item ou de `visible`. Ne pas réintroduire de mécanisme `setVisible` par item pour une future
visibilité par couche sans revoir « enregistrer l'image courante » (ADR-013).

## Règle « analyse du texte sur l'image d'origine »

Toute analyse du texte de la page (détection, OCR, segmentation, traduction) lit
`get_image_array(include_patches=False)` ; seul le nettoyage (`pipeline/inpainting.py`) lit
l'image avec patchs — il peint par-dessus des patchs déjà posés (ADR-016). Piège rencontré :
`app/controllers/manual_workflow.py` a des fins de ligne mixtes (CRLF/CR/LF) — l'éditer en octets,
sinon tout le fichier apparaît modifié dans le diff.

## Règle « le modèle de traduction ne coupe jamais les lignes »

`set_texts_from_json` (`modules/utils/translator_utils.py`) remplace tout saut de ligne renvoyé
par le modèle par une espace avant d'écrire `blk.translation` — c'est au rendu de couper le texte
selon la largeur de la bulle, jamais au modèle (hotfix `566740b`, ADR-017). Les traductions déjà
enregistrées avant ce correctif ne sont pas modifiées.

## Interdits

- Pas de compte, pas de télémétrie.
- Aucun appel réseau hors téléchargement de modèles (HuggingFace) et
  l'endpoint LLM configuré par l'utilisateur.
- Aucune page de BD dans git (`bench/pages/`, `bench/out/`, `*.cbz` ignorés).
- Pas de support Windows à ajouter.

## Défauts amont connus (ne pas « corriger par surprise », voir specs/decisions.md)

- Lecture de widgets Qt depuis le thread worker (pas de fil ouvert dans ce lot ;
  motif repris tel quel par `cleaning_config_from_settings_page`).
- Patchs webtoon découpés sans marge (`pipeline/webtoon_batch/chunk.py`), non
  corrigé — candidat PR amont (spec 00 §5).
- Fuite d'identifiants : décocher « Save Keys » n'efface pas les clés déjà
  écrites en clair dans QSettings (ADR-005, reporté, hors périmètre spec 01).
- `tests/test_app.py` cassé au commit de base : `setWindowTitle("Comic Translate[*]")`
  vs assertion `"Comic Translate"` (`app/ui/main_window/window.py:72`).
- Locale numérique fr_FR + onnxruntime : `QApplication` applique `LC_NUMERIC` système (virgule
  décimale) ; onnxruntime, importé plus tard (imports paresseux), renvoie alors une sortie
  constante (blanc) pour le modèle de reconnaissance PP-OCR — OCR silencieusement vide. Corrigé
  dans le fork (`comic.py`, `locale.setlocale(locale.LC_NUMERIC, "C")` juste après la création de
  `QApplication`, ADR-009). **Règle** : tout script qui crée une `QApplication` avant d'importer
  `onnxruntime` doit remettre `LC_NUMERIC` à `C` juste après.
- Environnement (Air) : « No route to host » (Errno 65) vers le Mini alors que `curl` passe = le
  réglage « Réseau local » de macOS bloqué dans un mauvais état. Tout binaire non signé Apple
  (Python système ou `uv`, Node) est refusé vers tout le LAN, box comprise ; Internet passe ; même
  échec depuis iTerm et Terminal.app, iTerm autorisé, Little Snitch désactivé. Pas un défaut de
  code. Seul correctif constaté : **redémarrer l'Air** (vu 2026-09-14/15 et 2026-09-23/24). Test :
  `uv run python -c "import urllib.request;print(urllib.request.urlopen('http://daaminim4.local:11434/api/version',timeout=5).read())"`.
- Navigation pendant un lot → corruption de page : `batch_processor.py:97` capture la page affichée
  au début du traitement ; naviguer pendant le lot fait écrire les blocs d'une page dans
  `image_states` d'une autre à la navigation suivante (ADR-014, non reproduit en réel).
- Même défaut hors lot sur les opérations multi-pages (Reconnaître/Traduire/Détecter sur sélection,
  `context["current_file"]` périmé si on navigue pendant l'opération, ADR-014).
- ~~`_batch_active` bloqué à `True` après un lot annulé avant démarrage~~ : **corrigé dans le fork**
  (`task_runner.py`, 2b-bis, ADR-019) — candidat PR amont.
- Page insérée puis traitée par lot : `viewer.load_state` lève `KeyError` sur `state['rectangles']`
  au chargement suivant (`viewer_state` incomplet laissé par le lot, ADR-014, touchera le jalon 4
  de la spec 04).
- Plantage natif intermittent (`Fatal Python error: Segmentation fault`) dans les tests de lot :
  bug **PySide6/Shiboken6 6.11.2** (`QGraphicsOpacityEffect` créé pendant la dépêche d'un autre
  événement, `dayu_widgets/tool_button.py:57`), pas du fork. Ne se reproduit pas sous
  `.venv/bin/python -m pytest` (voir commande ci-dessus), ni sous `COMIC_SHELL=0`. Détail : ADR-018.
- Macro d'annulation orpheline après un nettoyage/segmentation en échec ou une navigation pendant
  l'opération (`endMacro` vise `activeStack()` à la fin, pas la pile de départ) — décidée par
  Philippe, correction à venir (3a-bis, ADR-020).
- Annulations de texte (`TextEditCommand`, `RestoreVersionCommand`, `TextFormatCommand`) qui visent
  un item détruit après navigation ou reset de page → `RuntimeError` à l'annulation (MAJ1) —
  décidée par Philippe, correction à venir (3a-ter, ADR-020).

## Mémoire projet

Lire `JOURNAL.md` (chronologie des sessions) et `specs/decisions.md` (ADR, le *pourquoi*) avant
de proposer un changement. Specs exécutables sous `specs/`. Inventaire lecture seule de
l'historique de page et des calques : `specs/03-inventaire.md`.
