# Spec 00 — Fork « comic-translate » : feuille de route

> **STATUT : rédigée le 2026-09-11 (Claude Desktop), à valider par Philippe.**
> Document de cadrage, **pas** une spec d'implémentation : il ne se lance pas avec `/start`.
> Les specs exécutables sont `01`, `02`, `03`.

**Objectif** : lire en français des BD anglaises achetées (CBZ), avec une traduction **100 % locale**
(Ollama sur le Mac Mini), et améliorer l'application Comic Translate là où elle est faible.

**Usage** : strictement personnel. Aucune page de BD n'est versionnée dans le dépôt.

---

## 1. Base du fork — décision à valider

| Candidat | Commit | Compte obligatoire | Remarque |
|---|---|---|---|
| `ogkalu2/comic-translate` (officiel) | `8977b91` = tag **v2.8.9** (2026-09-10) | **Oui**, même en traducteur Custom | Validation `is_logged_in()` dans `modules/utils/pipeline_config.py` depuis le commit `3bb8fd3` (2026-01-28, v2.6.0) |
| `filvyb/comic-translate` (communautaire) | `059046d` (2026-07-10) | **Non**, aucun code d'authentification | Suit l'officiel sans le modèle d'abonnement |

**Retenu : `filvyb`** (fork créé le 2026-09-12), `ogkalu2` gardé en remote `upstream` pour
récupérer des correctifs au cas par cas. Licence Apache-2.0 des deux côtés : conserver `LICENSE`
et les mentions d'origine.

⚠️ Le README de filvyb affiche encore `git clone https://github.com/ogkalu2/comic-translate` : piège.

## 2. Ce qui EXISTE déjà dans l'app — vérifié dans le code (filvyb `059046d`)

À ne pas réimplémenter. Philippe ne les avait pas trouvés, c'est un problème de découvrabilité,
pas de fonctionnalité.

| Besoin exprimé | Existant | Où |
|---|---|---|
| Reprendre le travail plus tard | **Projets `.ctpr`** : Nouveau projet / Enregistrer le projet / Enregistrer sous. Sauvegarde par page : blocs (texte original, traduction, positions), historique d'images, patchs de nettoyage | `app/projects/project_state_v2.py`, `app/controllers/projects.py` |
| Ne pas perdre son travail | **Sauvegarde auto** dans un dossier + **instantanés de récupération** toutes les N minutes | Réglages > Projet (`app/ui/settings/project_page.py`) |
| Retrouver le texte original | Champ **source** (gauche) et champ **traduction** (droite) du bloc sélectionné | `s_text_edit` / `t_text_edit`, `app/ui/main_window/builders/workspace.py` |
| Calques façon Photoshop | **Export PSD** en 3 groupes : Texte éditable → Patchs de nettoyage → Image brute. **Import PSD** présent aussi | `app/controllers/psd_exporter.py`, `psd_importer.py` |
| Annuler | Annuler / Rétablir (pile Qt) | `undo_group` |

**Non vérifié** : la pile d'annulation ne semble **pas** sauvegardée dans le `.ctpr` (aucune
occurrence de `undo` dans `app/projects/`). À confirmer en conception de la spec 03.

**Découvrabilité OCR relevée le 2026-09-13** (voir spec 03 « Découvrabilité OCR ») : « Reconnaître »
sort en silence s'il n'y a aucun rectangle sur la page ; le résultat n'est visible que dans le
champ source après sélection d'un bloc ; langue source « Auto » colle les lignes sans espaces
(« English » donne un texte propre).

## 3. Décisions déjà prises (2026-09-11/12) — ne pas remettre en cause

- **Traduction locale** : Ollama sur le Mini, `http://daaminim4.local:11434/v1`, traducteur Custom.
- **Pas de relais HTTP** entre l'app et Ollama. Philippe : « une couche supplémentaire pour rien ».
  Toute adaptation de requête se fait **dans l'app**.
- **Modèle retenu : `translategemma:12b`** (Gemma 3, pas de capacité `thinking`). Mesures sur le
  banc `test_traduction.py` (6 cas, prompt identique à l'app) :

  | Modèle | Page de 8 bulles | JSON valide | Défauts relevés |
  |---|---|---|---|
  | `translategemma:latest` (4B) | 4,9 s | 6/6 | fautes d'accord (« ILS VIENT », « je arrive »), écriture inclusive, contresens d'onomatopée |
  | **`translategemma:12b`** | **13,8 s** | **6/6** | mineurs : juron dessiné traduit, onomatopée de tir |

- **Réflexion désactivée** : Gemma 4 et Qwen 3.5 réfléchissent par défaut sur `/v1` (Ollama v0.34.0
  l'active d'office si le modèle en est capable et que la requête ne dit rien). Mesuré : requête
  figée > 120 s sans `reasoning_effort`, **5,2 s pour 130 tokens** avec `"reasoning_effort": "none"`.
- **Rendu** : police **Patrick Hand** (OFL) pour les dialogues, option « Afficher le texte en
  majuscules » cochée. Sans elle, l'app convertit elle-même toute traduction en majuscules en
  minuscules (`set_upper_case`, `modules/utils/translator_utils.py`).

## 4. Lots

| Spec | Contenu | Dépend de |
|---|---|---|
| **01** | Socle : fork, lancement depuis les sources, SSL, traducteur Custom adapté à Ollama, banc de traduction | — |
| **02** | Nettoyage : remplissage uni, protection des bords de case, banc visuel | 01 |
| **03** | Historique et calques dans l'app — **conception d'abord** | 01 |
| 04 *(à écrire)* | Cœur headless + CLI (`ct translate album.cbz`) | 02 |
| 05 *(à écrire)* | Serveur MCP (FastMCP, version figée) au-dessus du cœur headless | 04 |
| 06 *(à écrire)* | Panneau de chat local (Ollama, appel d'outils) réutilisant les outils du MCP | 05 |

## 5. Idées en réserve (non spécifiées)

- **Locale numérique fr_FR + onnxruntime** (candidat PR amont prioritaire, mesuré le 2026-09-13) :
  `QApplication` applique `LC_NUMERIC` système, `onnxruntime` importé plus tard mésinterprète des
  flottants et rend l'OCR silencieusement vide en locale fr_FR (ou toute locale à virgule
  décimale). Corrigé dans le fork (`comic.py`, ADR-009) ; invisible pour des développeurs en
  locale anglaise, candidat naturel de PR amont.
- **Glossaire par album** (noms de personnages, termes récurrents) injecté dans le contexte.
- **Deux polices** : narration vs dialogue, choisies par classe de bloc (`text_free` / `text_bubble`).
- **Export direct vers Kavita** du CBZ traduit, ComicInfo compris (réutiliser l'existant de `daaLib`).
- **Retraduire une seule bulle** en gardant les versions précédentes (recoupe la spec 03).
- **Proposer en amont** (pull requests vers `ogkalu2`) les correctifs génériques : `certifi`,
  option « désactiver la réflexion » du traducteur Custom, alias de police `"Arial, Sans-serif"`
  (avertissement Qt au lancement, mesuré le 2026-09-12).
- `response_format: json_object` comme 4e option du traducteur Custom (candidat, non implémenté
  dans la spec 01 ; à évaluer si des réponses non-JSON persistent malgré `set_texts_from_json`).
- Candidats PR amont supplémentaires (mesurés dans la spec 01, 2026-09-12) : protection
  `json.loads` de `set_texts_from_json` (ne plus lever d'exception sur réponse malformée) et
  option de désactivation de la réflexion pour les traducteurs OpenAI-compatibles en général.
- Corriger la fuite d'identifiants QSettings constatée dans `settings_page.py` (ADR-005,
  `specs/decisions.md`) : décocher « Save Keys » n'efface pas les clés déjà écrites en clair.
- Attribution des composantes `sans_bloc` (spec 02, mode manuel) : composantes fragmentées ne
  touchant la graine d'aucun bloc (11 sur la page de référence). Jalon 2 (2026-09-13) a mesuré
  puis retiré deux mécanismes candidats — fusion des fragments par bloc (le gros de chaque
  légende est déjà une composante unique, les miettes restantes tombent sous `ring_min_pixels` de
  toute façon) et attribution par proximité (effet nul ou inconnu sur le corpus disponible), voir
  ADR-010. Colonnes CSV `aire_core`/`bbox_core`/`distance_bloc_le_plus_proche` ajoutées pour
  réévaluer sur mesure si le besoin réapparaît — non repris tant qu'aucune mesure ne le justifie.
- Bug amont `imkit/transforms.py:425-426` (mesuré spec 02 jalon 2, 2026-09-13) : surestime
  largeur/hauteur des composantes connexes de 1 px (bornes de mahotas déjà exclusives).
  Compensé côté `modules/cleaning/uniform.py` ; `imkit` non modifié — candidat PR amont.
- N3 (détection des cases, spec 02 §5) : seulement si le banc le justifie, via une colonne CSV
  `debord_case` mesurant les débordements résiduels sur les blocs restés en LaMa.
- Patchs webtoon découpés sans marge (`pipeline/webtoon_batch/chunk.py`) : défaut amont constaté
  pendant la spec 02, candidat PR amont plutôt que correctif local.
- Marge minimale bulle/texte avant appariement (`MIN_BUBBLE_MARGIN_PX = 3`,
  `modules/detection/base.py`, hotfix du 2026-09-15, ADR-011) : filtre générique contre les
  fausses bulles RT-DETR calées sur des légendes narratives, indépendant du fork Ollama —
  candidat PR amont.

## 6. Contraintes non négociables (tous lots)

1. **Aucune réintroduction** de compte, télémétrie ou appel réseau autre que : téléchargement des
   modèles (HuggingFace) et l'endpoint configuré par l'utilisateur.
2. **Code nouveau dans des modules nouveaux** autant que possible ; modifications des fichiers
   d'origine minimales et commentées `# fork:` pour faciliter les rebase sur `upstream`.
3. **Aucune page de BD dans git** : les pages de référence vivent dans `bench/pages/`, ignoré.
4. Environnement : macOS Apple Silicon, Python **3.12**, `uv`. Pas de support Windows à ajouter.
5. **Mesurer avant de postuler** : tout seuil (couleur, tolérance, timeout) est calibré sur des
   pages réelles et la mesure est consignée dans la spec.
