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
uv run pytest                                               # tests hors GUI (défaut)
QT_QPA_PLATFORM=offscreen uv run pytest --gui               # inclut tests/test_app.py
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
- Environnement : Little Snitch peut bloquer `python3.12` de `uv` vers le LAN (« No route to
  host » alors que `curl` passe, vu 2026-09-14/15, résolu par macOS 27 + redémarrage).

## Mémoire projet

Lire `JOURNAL.md` (chronologie des sessions) et `specs/decisions.md` (ADR, le *pourquoi*) avant
de proposer un changement. Specs exécutables sous `specs/`. Inventaire lecture seule de
l'historique de page et des calques : `specs/03-inventaire.md`.
