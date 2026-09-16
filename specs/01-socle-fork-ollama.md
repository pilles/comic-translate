# Spec 01 — Socle du fork : lancement local et traducteur Custom adapté à Ollama

> **STATUT : implémentée le 2026-09-12.**
> Prérequis : lire `00-feuille-de-route.md` (décisions §3, contraintes §6).
> Voir aussi `JOURNAL.md` (entrée du 2026-09-12) et `specs/decisions.md`
> (ADR-001 à ADR-006) pour le compte-rendu complet de la session.

**Objectif** : un fork qui se lance depuis les sources sur le Mac, télécharge ses modèles sans
erreur SSL, et traduit via Ollama **sans relais**, sans blocage par la réflexion des modèles.

**Contexte déclencheur** : trois pannes rencontrées le 2026-09-11 avec l'app empaquetée :
1. Détection impossible : `SSL: CERTIFICATE_VERIFY_FAILED` au téléchargement du modèle RT-DETR.
2. Traduction impossible : `Read timed out. (read timeout=120)` avec `gemma4:12b-mlx`.
3. Compte obligatoire pour utiliser un modèle local (app officielle).

---

## 1. Mise en place du fork

**Déjà fait le 2026-09-12** : fork de `filvyb/comic-translate` cloné dans
`/Users/daaone/_Claude/comic-translate`, remotes `filvyb` et `upstream` (→ `ogkalu2`) ajoutés,
dépendances installées par `uv`, app lancée avec succès (`uv run comic.py`).

**Fait le 2026-09-12** (ADR-002) : `requirements.txt` reste la seule source de vérité des
dépendances. `pyproject.toml` est **généré** — bloc `[project].dependencies` entre marqueurs
`# --- sync_deps: begin/end ---`, régénéré par `uv run python tools/sync_deps.py --write`,
vérifié par `--check` (défaut, exit 1 si désynchronisé). `uv.lock` et `.python-version` sont
versionnés. Conséquence assumée : diffs volumineux sur `pyproject.toml`/`uv.lock` et conflits
possibles sur `.gitignore` lors des rebase (`filvyb`/`upstream` ne connaissent pas ces fichiers).
Alternative rejetée : `dynamic = ["dependencies"]` (moins explicite pour `uv`, ne supprime pas le
besoin de vérification).

Fait aussi : URL de clonage du README corrigée (`https://github.com/pilles/comic-translate`) ;
`CLAUDE.md` du projet (carte des modules, règle `# fork:`, commandes).

## 2. F1 — Téléchargements : certificats

**Mesuré** : `modules/utils/download_file.py` ouvre les URL par `urllib.request.urlopen(req,
timeout=timeout)` (ligne 33) **sans contexte SSL**. Le Python embarqué ou géré ne trouve pas
toujours les racines de confiance de macOS.

**À vérifier d'abord** : l'erreur SSL a été constatée sur l'app **empaquetée**. Reproduire depuis
les sources (`uv run comic.py`, détection sur une page, cache de modèles vide). Si elle ne se
reproduit pas, F1 reste souhaitable (robustesse, contribution en amont) mais **perd sa priorité** —
le consigner ici plutôt que de supposer.

**Mesuré le 2026-09-12** (depuis les sources, Python 3.12.11 géré par `uv`, OpenSSL 3.0.16) :
`urlopen('https://huggingface.co/...')` sans contexte renvoie HTTP 200 ;
`ssl.get_default_verify_paths().openssl_cafile == '/private/etc/ssl/cert.pem'` existe. **La panne
ne se reproduit pas depuis les sources.** Sa cause sur le DMG n'a pas été diagnostiquée. F1 est
implémentée quand même (robustesse, contribution amont possible via `specs/00-feuille-de-route.md`
§5) mais en **priorité basse** — voir ADR-006. **Ne jamais écrire que F1 corrige la panne du DMG,
ni que le critère §6.1 ci-dessous valide F1** : ce critère porte sur le lancement depuis les
sources, où la panne ne s'est pas reproduite avant même l'implémentation de F1.

**Implémenté** : `modules/utils/ssl_context.py`, `get_ssl_context()` mémoïsé. Priorité : (1)
`SSL_CERT_FILE`/`SSL_CERT_DIR` défini → None (comportement utilisateur inchangé) ; (2) magasin
système présent (cafile ou capath) → None ; (3) `certifi` importable → contexte basé sur
`certifi.where()` ; (4) sinon None. Aucun chemin ne produit `CERT_NONE`. `certifi` ajouté comme
dépendance explicite dans `requirements.txt`. Branché dans `modules/utils/download_file.py`
(2 lignes `# fork:` : import + `context=get_ssl_context()` dans `_open_url`).

**Hors périmètre, consigné** : `pororo/models/brainOCR/utils.py:705` (`urlretrieve`, chemin mort)
et `pororo/tasks/utils/download_utils.py:292` (`wget`, OCR coréen) ne passent pas par ce contexte.

## 3. F2 — Traducteur Custom adapté à Ollama

**Mesuré dans le code** :
- `CustomTranslation` hérite de `GPTTranslation` (`modules/translation/llm/custom.py`).
- La requête envoie `model`, `messages`, `temperature`, `top_p`, **`max_completion_tokens`**
  (`gpt.py` l. 87) avec un **`timeout=80` codé en dur** (`gpt.py` l. 102).
- Aucun paramètre de réflexion n'est envoyé, aucun champ de l'interface ne permet d'en ajouter.

**Mesuré sur Ollama v0.34.0** (code du 2026-09-10) :
- Pas de réglage global de la réflexion (ni Modelfile, ni variable d'environnement).
- Si le modèle a la capacité `thinking` et que la requête ne précise rien, la réflexion est activée.
- Sur `/v1` : `reasoning_effort` accepte `none` ; la limite de longueur attendue est `max_tokens`.

**Demandé** — trois réglages dans la page Custom des identifiants, persistés comme les autres :

| Réglage | Défaut | Effet sur la requête |
|---|---|---|
| Désactiver la réflexion | **coché** | ajoute `"reasoning_effort": "none"` |
| Compatibilité Ollama (`max_tokens`) | **coché** | renomme `max_completion_tokens` → `max_tokens` |
| Délai d'attente (s) | **180** | remplace le `timeout` codé en dur, **pour Custom uniquement** |

Implémentation dans `custom.py` (surcharge de `_make_api_request` ou équivalent), **sans
modifier le comportement des traducteurs OpenAI/GPT**.

**Mesuré le 2026-09-12 avant de figer le défaut « coché »** (voir ADR-004 pour le détail) :
- T2 : `translategemma:12b` + `reasoning_effort: "none"` + `max_tokens` → HTTP 200, JSON valide,
  10 s. Confirme qu'envoyer `reasoning_effort: none` à un modèle **sans** capacité `thinking` ne
  dégrade rien : le défaut « coché » est **figé sans condition sur les capacités** (pas de lecture
  `/api/show`).
- T3 : `max_completion_tokens: 5` → HTTP 200 mais **ignoré** par Ollama (191 tokens générés,
  `finish_reason: "stop"`). `max_tokens: 5` → honoré (`finish_reason: "length"`). Confirme le
  renommage `max_completion_tokens` → `max_tokens` comme réglage « compatibilité Ollama ».
- `gemma4:12b-mlx` + `reasoning_effort: "none"` (`max_tokens: 300`) → JSON complet en 6,5 s.
  Témoin sans réglage → 300 tokens consommés dans le champ `reasoning`, `content` vide,
  `finish_reason: "length"` (reproduit la panne d'origine du 2026-09-11).

**Implémenté** : `modules/translation/llm/compat.py` — `OpenAICompatOptions` (dataclass gelée,
`disable_reasoning`/`use_max_tokens`/`timeout`, défauts `True`/`True`/180),
`from_credentials()` tolérant (bool natif, `"true"/"false"/"1"/"0"`, absent, `None`, valeurs
aberrantes → défaut), `adapt_payload()` pur (ne mute jamais l'entrée). `custom.py` surcharge
`_make_api_request` pour appeler `adapt_payload` puis déléguer à `GPTTranslation`. Le **timeout
est un entier unique** (`self.request_timeout = self._compat.timeout`), pas un tuple
connect/read : `GPTTranslation._make_api_request` ne distingue pas les deux, un tuple aurait
changé le contrat de la classe mère. `gpt.py` inchangé côté comportement (`max_completion_tokens`,
pas de `reasoning_effort`, timeout 80 s codé en dur) — seules 2 lignes `# fork:` marquent l'endroit
où `self.request_timeout` est défini et utilisé, pour que `custom.py` puisse le réassigner.

Réglages UI persistés dans QSettings (groupe `custom_llm`, indépendant de « Save Keys ») :
case à cocher réflexion désactivée, case à cocher `max_tokens`, champ numérique timeout
(bornes 10–1800, défaut 180 si valeur hors plage — `_coerce_timeout` dans `compat.py`).

**Protection ajoutée dans `set_texts_from_json`** (F3, mais motivée par F2) : garde d'entrée sur
type/vide et `json.loads` protégé par `try/except ValueError` — une réponse tronquée ou
non-JSON (cas T3, ou `gemma4:12b-mlx` sans réglage) ne doit plus lever d'exception jusqu'à l'UI,
seulement logguer un avertissement et laisser la page non traduite.

**Hors périmètre** : relais HTTP (refusé, spec 00 §3), prise en charge du streaming.

## 4. F3 — Banc de traduction

Intégrer le banc écrit le 2026-09-11 (`test_traduction.py`) sous `tools/bench_translation.py` :
- **Réutiliser le vrai code de l'app** pour construire le prompt et parser la réponse
  (`get_system_prompt`, message utilisateur, `set_texts_from_json`), au lieu de le recopier :
  le banc doit casser si l'app change son format.
- Options : `--url`, `--model`, `--temperature`, `--context`, `--cases fichier.yaml`.
- Cas par défaut : les 6 cas existants (dialogue, familier, MAJUSCULES, onomatopées, fautes
  d'OCR, page de 8 bulles), **phrases inventées uniquement**.
- Sortie : tableau par cas (temps, statut JSON, clés manquantes) + export CSV optionnel pour
  comparer des modèles.
- Détection explicite : 404 (modèle absent), JSON invalide, clé manquante, dépassement du
  délai configuré.

**Implémenté, résultats (via le Mini, vrai chemin de code de l'app)** :
- `translategemma:12b` : 6/6 OK, cas de 6,4 à 7,2 s, page de 8 bulles 13,7 s, exit 0.
- `gemma4:12b-mlx` (réflexion désactivée) : 6/6 OK, 2,4 à 8,3 s, page de 8 bulles 5,8 s.
- Incident pendant la session : le runner Ollama de `translategemma:12b` a renvoyé des réponses
  vides (`done: false`) pendant ~20 min avant de récupérer seul (expiration/rechargement du
  modèle) — premier passage du banc 1/6 pour cette raison, pas un défaut de code.
- Classification étendue au-delà de la conception initiale (14 statuts ordonnés, cf.
  `tools/bench_translation.py` : `CONNEXION_REFUSEE`, `INJOIGNABLE`, `TIMEOUT`, `MODELE_ABSENT`,
  `ERREUR_HTTP`, `TRONQUE`, `JSON_INVALIDE`, `JSON_NON_EXTRAIT`, `PAS_DE_JSON`,
  `CLES_MANQUANTES`, `TYPE_INATTENDU`, `VIDE`, `NON_TRADUIT`, `OK`, + `ERREUR_INATTENDUE` en
  secours).

## 5. Tests

Fichiers réels sous `tests/` :
- `conftest.py` — option `--gui`, exclusion de `test_app.py` sans `--gui`, faux serveur HTTP local.
- `test_ssl_context.py` (8 cas) — les 4 priorités de `get_ssl_context`, `_open_url` transmet
  `context=`.
- `test_llm_payload.py` (7 cas) — `adapt_payload`/`from_credentials`, non-régression GPT.
- `test_prompt_contract.py` (4 cas) — `build_user_prompt`, `get_raw_text`, `get_system_prompt`.
- `test_set_texts_from_json.py` (8 cas) — JSON propre, Markdown, clé manquante, malformé, None/vide.
- `test_bench_classification.py` (21 cas) — les 14 règles de classification, ordre de sévérité.
- `test_bench_translation.py` (13 cas) — bout en bout sur le faux serveur local (tous les statuts,
  CSV, exit code).
- `test_dependencies_sync.py` (5 cas) — `tools/sync_deps.py --check`.
- `test_app.py` — inchangé, exclu par défaut (voir §6 et « Défauts connus hors périmètre »).

Résultat : `uv run pytest -q` → **86 passed** (~16 s, hors `--gui`). Détail dans `JOURNAL.md`
(entrée 2026-09-12).

## 6. Critère de réussite

1. Détection sur une page depuis les sources, cache de modèles vide, **sans** variable
   d'environnement SSL. — **Validé** (la panne SSL du DMG ne s'est pas reproduite depuis les
   sources ; **ce constat ne valide pas F1**, voir ADR-006).
2. Page réelle traduite avec `gemma4:12b-mlx` **et** `translategemma:12b` via le Mini, sans
   dépassement de délai, sans compte. — **Validé** via le banc (§4).
3. `uv run python tools/bench_translation.py --model translategemma:12b` : 6/6 `OK`. — **Validé**
   (6,4–7,2 s par cas, 13,7 s page 8 bulles ; premier passage 1/6 dû à un incident Ollama
   indépendant du code, cf. §4).
4. Tests verts ; le diff par rapport au commit de base du fork (`059046d`) ne touche que les
   fichiers listés ici et des modules nouveaux. — **Validé** : 86/86 tests hors GUI ;
   11 fichiers d'origine modifiés (106 insertions, 35 marqueurs `# fork:`), tous listés dans
   `CLAUDE.md` ; reste nouveaux modules/outils/tests + `pyproject.toml`/`uv.lock`/`.python-version`.
   `test_app.py` (`--gui`) échoue déjà au commit de base, hors critère (voir ci-dessous).

## Défauts connus hors périmètre

- **Fuite d'identifiants QSettings** (ADR-005) : décocher « Save Keys » n'efface pas les clés déjà
  écrites en clair (`settings_page.py`, préexistant à `059046d`). Reporté.
- **`tests/test_app.py`** cassé au commit de base : `setWindowTitle("Comic Translate[*]")`
  (`app/ui/main_window/window.py:72`) vs assertion `"Comic Translate"`. Non corrigé dans ce lot.
- **Lecture de widgets Qt depuis le thread worker** : défaut d'origine, non traité (pas dans le
  périmètre spec 01, à traiter si un lot ultérieur touche au threading).
