# Spec 03 — Inventaire de l'existant (lecture seule)

> **Date : 2026-09-13.** Établi par lecture du code au commit de travail (base `filvyb 059046d`,
> fork non commité), complété par les mesures du §8. Chaque affirmation est appuyée sur
> `fichier:ligne`. Périmètre : contrat du §2 de `specs/03-historique-et-calques.md`.
>
> Rappel des besoins exprimés (spec 03, 2026-09-11 et 2026-09-13) : reprendre une page plus tard,
> retrouver le texte original, calques façon Photoshop, historique de page, **« se tromper et
> revenir en arrière pour corriger »**, **« interface simple mais pas pauvre »**.
>
> Note de périmètre : `app/projects/*`, `app/ui/commands/*`, `app/controllers/{image,text,projects,
> psd_*}.py`, `controller.py` ne portent **aucune ligne `# fork:`** — ce qui est décrit ici est
> donc aussi le comportement de l'application d'origine (`filvyb 059046d`).

---

## 1. Réponses au tableau du §2

### 1.1 Que contient le `.ctpr` ?

Format réel : **base SQLite** (et non une archive ZIP), détectée par son en-tête
(`app/projects/project_state_v2.py:19`, `:26-34`). L'écriture passe toujours par v2
(`app/projects/project_state.py:43-45`) ; la lecture choisit v2 si l'en-tête SQLite est présent,
sinon le chemin ZIP hérité (`app/projects/project_state.py:62-64`, `:83-104`).

Tables (`project_state_v2.py:45-107`) :

| Table | Contenu | Ligne |
|---|---|---|
| `meta` | clé/valeur ; une seule clé écrite : `project_format_version = "2"` | `:46-53`, `:413-416` |
| `project_manifest` | blob msgpack, 1 ligne (manifeste global) | `:55-61`, `:418-425` |
| `page_state` | 1 ligne par page (`page_path` → blob msgpack) | `:62-69`, `:436-442` |
| `project_state` | table héritée d'un format v2 intermédiaire, lue seulement en repli | `:70-78`, `:662-699` |
| `blobs` | images et patchs PNG (`hash`, `kind`, `ext`, `size`, `data`) | `:79-89`, `:318-321` |
| `source_fingerprints` | `path`/`size`/`mtime_ns`/`hash`, cache pour éviter de relire les fichiers | `:90-99`, `:446-453` |
| `batch_report` | blob msgpack du dernier rapport de lot | `:100-107`, `:456-460` |

**Manifeste** (`:388-398`), clés exactes : `current_image_index`, `original_image_files`,
`current_history_index`, `displayed_images`, `loaded_images`, `llm_extra_context`, `webtoon_mode`,
`webtoon_view_state`, `unique_images`.

**Ligne de page** (`:376-386`), clés exactes : `image_state`, `image_file_ref`, `image_data_ref`,
`image_history_refs`, `in_memory_history_refs`, `patches`.

**`image_state`** est le dict construit par `app/controllers/image.py:64-91`
(`_build_image_state`) : `viewer_state`, `source_lang`, `target_lang`, `brush_strokes`,
`blk_list`, `skip`, `export_group_name`. Le lot webtoon y ajoute `skip_render`
(`pipeline/webtoon_batch/render.py:37`, `:49`).

**`viewer_state`** (`app/ui/canvas/image_viewer.py:502-531`) : `rectangles`, `transform`,
`center`, `scene_rect`, `text_items_state` (+ `push_to_stack`, ajouté par le rendu,
`app/controllers/text.py:894`, `pipeline/batch_processor.py:432-434`).

**Format des patchs** : à l'enregistrement, chaque patch devient
`{"bbox": [...], "png_hash": <sha256 du PNG>, "hash": <hash composite image+bbox>}`
(`project_state_v2.py:357-364`) ; le PNG lui-même part dans `blobs`. À la relecture, le patch est
reconstruit en `{"bbox", "png_path", "hash"}` avec un chemin **paresseux** dans
`temp_dir/unique_patches/<page>/<idx>_<hash12>.png`, matérialisé à la demande
(`:594-621`, `:187-223`).

**Historique d'images** : seules des **références** (identifiants d'images uniques) sont stockées
(`image_history_refs`, `in_memory_history_refs`, `:338-356`) ; les pixels correspondants vont dans
`blobs` (`:326-336`). L'index courant est global au manifeste (`current_history_index`, `:391`).

**Ce qui n'est PAS dans le `.ctpr`** :
- **aucune pile d'annulation** : `grep -n "undo" app/projects/` ne renvoie rien ;
- **aucun cache OCR/traduction** : ces caches vivent en mémoire dans le processus
  (`pipeline/cache_manager.py:10-12`) et ne sont jamais sérialisés ;
- **aucun réglage de traitement par page** hors langues (voir §1.6) ;
- **aucun journal d'opérations** hors le rapport de lot (§1.6).

Note de compatibilité : les chemins absolus locaux des pages sont écrits en clair
(`original_image_files`, clés de `page_state`, `source_fingerprints.path`) — après un
premier chargement ils pointent vers `temp_dir` (`:563`, `:472-479`).

### 1.2 Le texte original de chaque bloc est-il rechargé ? — **Oui**

`blk_list` est sérialisé dans `image_state`, chaque `TextBlock` étant encodé par son
`__dict__` complet (`app/projects/parsers.py:57-63`) et restauré par
`TextBlock().__dict__.update(...)` (`parsers.py:174-178`). Les champs `text` (source OCR) et
`translation` en font partie (`modules/utils/textblock.py:46-47`).

Où il s'affiche : **champ source `s_text_edit` uniquement après sélection d'un bloc**, par deux
chemins — sélection d'un rectangle (`app/controllers/rect_item.py:51-60`) ou sélection d'un item
de texte (`app/controllers/text.py:193-196`). Les deux champs sont toujours visibles dans la
fenêtre (`app/ui/main_window/builders/workspace.py:154-166`), mais **vidés à chaque changement de
page** (`app/controllers/image.py:1129` → `text.py:95-99`) et **vidés après « Rendre »**
(`text.py:929`, `:948-949`). Aucune étiquette texte « Source » / « Traduction » : seules les
listes de langues ont une infobulle (`workspace.py:152`, `:162`).

Piège confirmé en lecture : après « Rendre », les rectangles sont effacés (`text.py:947`) ; il
faut `Ctrl+Shift+R` (`app/shortcuts.py:47-52` → `controller.py:326-337`) pour les redessiner et
pouvoir re-sélectionner un bloc.

### 1.3 La traduction précédente d'un bloc est-elle conservée après retraduction ? — **Non**

`TextBlock.translation` est un **champ scalaire unique** (`modules/utils/textblock.py:47`) ;
aucune notion de version, d'historique ou d'horodatage dans la classe (`:14-112`). Il est écrasé
en place par :
- la traduction LLM (`modules/utils/translator_utils.py:70`) ;
- la reprise de cache (`pipeline/translation_handler.py:56`, `:87`, `pipeline/cache_manager.py:346`) ;
- la mise en casse, à chaque rendu (`translator_utils.py:78-100`, `format_translations` /
  `set_upper_case`) — la version d'avant majuscules est perdue ;
- l'édition manuelle (`app/controllers/text.py:250`, `:261`, `:284`, `:467`) ;
- le Rechercher/Remplacer (`app/controllers/search_replace.py:961`, `:991`) ;
- le lot, qui remplace `blk_list` entier pour la page (`pipeline/batch_processor.py:441-443`).

Seule l'**édition manuelle** est réversible, et uniquement dans la session : `TextEditCommand`
garde `old_text`/`old_html` (`app/ui/commands/text_edit.py:4-23`), poussée après un délai de 400 ms
(`text.py:43-46`, `:428-452`). Une **retraduction** ne pousse aucune commande (§2).

Garde-fou existant, à ne pas confondre avec une version : en mode bloc unique, OCR et traduction
**refusent d'écraser** un champ déjà rempli (`pipeline/ocr_handler.py:37-39`,
`pipeline/translation_handler.py:47-49`).

### 1.4 La pile Annuler/Rétablir survit-elle à la réouverture ? — **Non** (hypothèse de la spec confirmée)

Les piles sont des `QUndoStack` en mémoire, une par chemin de page
(`controller.py:94-95`), rattachées à un `QUndoGroup` unique. Elles sont **recréées vides** à
chaque chargement de projet (`app/controllers/projects.py:1309-1314`) et à chaque chargement
d'images (`app/controllers/image.py:511-522`, `:405-414`, `:460-464`). Rien dans `app/projects/`
ne les lit ni ne les écrit.

Précisions utiles pour la suite :
- **Pas de vidage au changement de page** : aucune occurrence de `QUndoStack.clear()` dans le
  dépôt ; `display_image` se contente de changer la pile active
  (`app/controllers/image.py:1147-1148`, aussi `:655-656`). La pile d'une page survit donc à un
  aller-retour de page **dans la session**.
- Vidage complet à `clear_state()` (`image.py:311`), appelé avant tout chargement d'images ou de
  projet (`image.py:370`, `projects.py:1364`, `:469`).
- Défaut constaté : `clear_state()` vide le dictionnaire `undo_stacks` mais n'appelle jamais
  `undo_group.removeStack()` (seul `handle_image_deletion` le fait, `image.py:844-846`) — les
  anciennes piles restent référencées par le groupe après un rechargement. Sans effet fonctionnel
  visible, mais c'est une fuite mémoire par projet ouvert.
- « Enregistrer » ne vide pas la pile : `set_project_clean()` appelle `stack.setClean()`
  (`controller.py:385-392`), ce qui ne fait que déplacer le repère de propreté.

### 1.5 Page nettoyée puis re-nettoyée : patchs **empilés**, jamais remplacés

`PatchInsertCommand._register_patches` n'écarte que les **doublons exacts** (même hash composite
image+bbox) et sinon **ajoute** à `image_patches[file_path]`
(`app/ui/commands/inpaint.py:62-78`). Le hash est un sha256 des octets du PNG **plus** la bbox
(`:37-40`) : un second nettoyage de la même zone produit presque toujours un contenu différent,
donc un patch supplémentaire superposé.

À l'affichage, chaque patch est un `QGraphicsPixmapItem` distinct posé à `Z = 0.5`
(`app/ui/commands/base.py:250-261`) : les patchs récents masquent les anciens, aucun n'est
supprimé. Au rechargement de page, tous les patchs enregistrés sont redessinés
(`app/controllers/image.py:984-1008`). À l'export image, ils sont réappliqués dans l'ordre de la
liste (`app/controllers/projects.py:917` → `app/ui/canvas/save_renderer.py:238-261`).

Conséquence mesurable (§7.3) : la taille du `.ctpr` croît à chaque nettoyage répété d'une même page.

Le nettoyage **est** annulable : la séquence est encadrée par une macro `"inpaint"`
(`app/controllers/manual_workflow.py:605`, fermée par `pipeline/inpainting.py:815`), qui contient
`PatchInsertCommand` et le `ClearBrushStrokesCommand` du nettoyage des tracés
(`inpainting.py:812-815`). Asymétrie relevée sur le chemin multi-pages : `state['brush_strokes']`
est vidé **hors** commande (`manual_workflow.py:579-581`), donc non restauré par Annuler.

### 1.6 Réglages de traitement mémorisés par page

| Réglage | Mémorisé par page ? | Preuve |
|---|---|---|
| Langue source | **Oui** | `image.py:75-79` (`source_lang`), rechargée `image.py:1056-1059`, `:1077-1079` |
| Langue cible | **Oui** | `image.py:80-83`, `:1080-1082` |
| Nom de groupe d'export | Oui | `image.py:87-89` |
| Page ignorée (`skip`) | Oui | `image.py:86` |
| Tracés de pinceau | Oui | `image.py:84` (`brush_strokes`) |
| **Modèle de traduction / traducteur** | **Non** | aucune clé ; lu à la volée depuis `settings_page.get_tool_selection('translator')`, `pipeline/translation_handler.py:31` |
| **Contexte LLM (`extra_context`)** | **Non, projet entier** | une seule valeur globale dans le manifeste (`project_state_v2.py:394`), restaurée dans la page Réglages (`projects.py:1397-1398`) |
| **Modèle OCR** | **Non** | `pipeline/ocr_handler.py:26` |
| **Inpainter / stratégie HD** | **Non** | lu à la volée, `pipeline/inpainting.py:774-777`, `:707-712` |
| **Réglages de nettoyage du fork** (`uniform_fill`, `protect_lines`, `free_dilate_iterations`) | **Non** | `cleaning_config_from_settings_page(settings_page)`, `pipeline/inpainting.py:674` — lecture des widgets à chaque appel |
| **Police / rendu** | **Non, global QSettings** | `projects.py:1403`, `:1462-1492` |

Le seul artefact horodaté persisté est le **rapport de lot** :
`started_at`, `finished_at`, `was_cancelled`, `total_images`, `skipped_count`, `completed_count`,
`skipped_entries[{image_path, image_name, reasons[]}]`
(`app/controllers/batch_report.py:236-261`), sérialisé dans la table `batch_report`
(`project_state_v2.py:403-408`, relu `:716-733`). Il ne contient **ni modèle, ni réglage, ni
opération réussie** — uniquement les pages sautées et leur motif.

### 1.7 Aller-retour PSD : export → retouche → import

**Export** (`app/controllers/psd_exporter.py:84-138`), 3 groupes, ordre visuel haut → bas :
`Editable Text` (`:94-106`) → `Inpaint Patches` (`:109-120`) → `Raw Image` (`:122-131`).
Source des données : `viewer_state['text_items_state']` et `image_patches` capturés avant export
(`projects.py:932-975`), **pas** la scène affichée.

**Import** (`app/controllers/psd_importer.py:78-109`) :

| Élément | Conservé à l'import ? | Preuve |
|---|---|---|
| Image de base | Oui (`Raw Image`) | `psd_importer.py:84-91` |
| Texte éditable | Oui, reconstruit en `text_items_state` (police, taille, couleur, contour, alignement, direction, rotation) | `:99-109`, `:475-537` |
| **Patchs de nettoyage** | **Non en tant que couche** : fusionnés dans l'image de base | `:95-97` (`_blend_image_layer(rgb_image, patch_layer)`) |
| **`blk_list`** (texte source OCR, traduction, classe, bbox, angle) | **Non : perdu** | `app/controllers/image.py:397-403` — `_build_image_state(..., [], [], False)` |
| Rectangles de détection | Non | `psd_importer.py:55` (`"rectangles": []`) |
| Langues source/cible de la page | Non (valeurs courantes de l'interface) | `image.py:397-403` |
| Historique d'images | Non : réinitialisé à une seule entrée | `image.py:394-396` |

Un PSD non produit par l'application est aplati et signalé par un avertissement
(`psd_importer.py:92-93`, `:129-136`). Un PSD de l'application contenant des fonctionnalités
Photoshop non gérées (masques, objets dynamiques, modes de fusion, opacité) déclenche aussi un
avertissement (`:139-161`).

**Conclusion** : l'aller-retour PSD conserve le *rendu* (image + texte éditable), pas l'*état de
travail* (blocs, texte source, traductions, patchs séparés). Un import PSD n'est donc pas un
chemin de reprise de travail.

---

## 2. Ce qui est annulable aujourd'hui — et ce qui ne l'est pas

### 2.1 Les 16 `QUndoCommand` existantes

| Commande | Fichier | Ce qu'elle restaure | Déclencheur |
|---|---|---|---|
| `AddRectangleCommand` | `commands/box.py:11-37` | rectangle de scène + `TextBlock` associé dans `blk_list` | tracé manuel d'une boîte (`rect_item.py:66-76`) |
| `BoxesChangeCommand` | `box.py:39-98` | bbox, angle, origine de transformation (item **et** bloc) | déplacement/rotation/redimensionnement (`rect_item.py:102-105`) |
| `ResizeBlocksCommand` | `box.py:101-156` | toutes les bbox de la page (± diff) | « agrandir/réduire tous les blocs » (`text.py:365-374`) |
| `ClearRectsCommand` | `box.py:158-177` | tous les rectangles supprimés | bouton « effacer les rectangles » (`interaction_manager.py:217`) |
| `DeleteBoxesCommand` | `box.py:179-221` | rectangle + item de texte + `TextBlock` | touche Suppr (`controller.py:445-468`) |
| `AddTextItemCommand` | `box.py:223-239` | item de texte rendu | rendu d'un bloc (`text.py:171-172`), restauration d'état (`image.py:1092`, `:1240`) |
| `ReplaceDetectedBlocksCommand` | `box.py:242-311` | **`blk_list` complet avant/après détection** + rectangles + état de page | détection page seule, hors webtoon (`pipeline/block_detection.py:191-200`) |
| `BrushStrokeCommand` | `brush.py:6-24` | un tracé de pinceau | fin de tracé (`drawing_manager.py:84`) |
| `SegmentBoxesCommand` | `brush.py:26-45` | tracés de segmentation | `drawing_manager.py:383` |
| `ClearBrushStrokesCommand` | `brush.py:47-66` | tous les tracés effacés | `drawing_manager.py:244`, et dans la macro « inpaint » |
| `EraseUndoCommand` | `brush.py:68-163` | état complet des tracés avant/après gomme | `drawing_manager.py:110` |
| `SetImageCommand` | `commands/image.py:7-111` | image de page + position dans `image_history` | **chemin mort**, voir §3 |
| `ToggleSkipImagesCommand` | `image.py:114-147` | drapeau `skip` d'une ou plusieurs pages | `image.py:943` |
| `PatchInsertCommand` | `inpaint.py:8-144` | groupe de patchs (`image_patches`, `in_memory_patches`, items de scène) | fin de nettoyage (`image.py:1319`, `:1323`) |
| `TextEditCommand` | `text_edit.py:4-23` | texte **et** HTML d'un item, plus `blk.translation` | édition du champ traduction / de l'item, après 400 ms (`text.py:428-452`) |
| `TextFormatCommand` | `textformat.py:4-42` | HTML + `__dict__` de l'item (police, taille, couleur, contour, styles, alignement, interligne) | `text.py:226`, `:501-611` |
| `ReplaceBlocksCommand` | `search_replace.py:19-53` | texte source **ou** cible de N blocs, multi-pages | Rechercher/Remplacer (`search_replace.py:1118`, `:1211`) |

Macros nommées existantes : `"inpaint"` (`manual_workflow.py:571`, `:605`), `"render_text"`
(`text.py:763`), `"text_items_rendered"` (`image.py:1090`, `:1238`),
`"draw_segmentation_boxes"` (`manual_workflow.py:623`), `"delete_selected_boxes"`
(`controller.py:455`), `"change_text_*"` (`text.py:485-517`).

### 2.2 Ce qui n'est PAS annulable

| Opération | Preuve |
|---|---|
| **OCR** (page entière ou bloc unique) | `pipeline/ocr_handler.py:80`, `:86`, `:92-94` — écriture directe de `blk.text` ; multi-pages `manual_workflow.py:270-272`, `:281` |
| **Traduction** (page, bloc, lot) | `pipeline/translation_handler.py:56`, `:87`, `:95`, `:99-103` ; multi-pages `manual_workflow.py:391` ; lot `batch_processor.py:441-443` |
| **Détection** en mode webtoon ou multi-pages | `block_detection.py:202-203` ; `manual_workflow.py:182` |
| **Mise en casse** du rendu | `translator_utils.py:78-100`, appelée par `text.py:824` et `:967` hors commande |
| **Traitement par lot complet** | `batch_processor.py:428-443` écrit directement dans `image_states` ; seuls les patchs (`:326-327`) et les items de texte (`:393`) passent par des commandes |
| Changement de langue source/cible d'une page | `text.py:338-354`, `:356-363` |
| Réordonnancement / suppression de pages | `image.py:619-659`, `:810-916` |
| Vidage de `brush_strokes` du multi-pages | `manual_workflow.py:579-581` |

**Traduction de la demande de Philippe** (« se tromper et revenir en arrière pour corriger ») :
aujourd'hui, on peut revenir en arrière sur ce qu'on a fait **à la main** (boîtes, tracés, texte,
mise en forme, nettoyage) mais **pas sur ce que la machine a produit** (OCR, traduction,
détection en lot) — sauf la détection page seule.

### 2.3 Où la pile est-elle vidée ?

- **Jamais** au changement de page (seul le `setActiveStack` change, `image.py:1147-1148`).
- **À chaque chargement** d'images, de PSD ou de projet, via `clear_state()`
  (`image.py:289-322`, ligne `:311`), suivi de la création de piles neuves.
- À la suppression d'une page, pour cette page seulement (`image.py:844-849`).
- Une restauration d'instantané de récupération passe aussi par `clear_state()` (`projects.py:469`).

---

## 3. Historique d'images : mécanisme exact

**Structures** (`controller.py:85-91`) : `image_history: dict[str, list[str]]` (chemins de
fichiers ; l'entrée 0 est le fichier d'origine, les suivantes des PNG temporaires) ;
`in_memory_history: dict[str, list[np.ndarray]]` (tableaux en mémoire, même indexation) ;
`current_history_index: dict[str, int]` ; `max_images_in_memory = 5` (`image.py:966-971`).

**Initialisation** : à chaque premier affichage d'une page,
`image_history[p] = [p]`, `in_memory_history[p] = [copie]`, `current_history_index[p] = 0`
(`image.py:951-960`, aussi `:503-508`, `:394-396`, `:444-447`).

**Qui crée une entrée supplémentaire** : uniquement
`SetImageCommand.update_image_history` (`commands/image.py:77-103`). Son unique appelant est
`ImageStateController.set_image` (`image.py:973-982`), lui-même appelé **uniquement** depuis
`on_image_processed` (`image.py:1181-1193`), branché sur le signal `image_processed`
(`controller.py:46`, `:131`). **Ce signal n'est émis nulle part dans le dépôt** (3 occurrences,
aucune `.emit`). Conclusion : **l'historique d'images n'a en pratique qu'une seule entrée par
page**, et `SetImageCommand` est du code mort dans cette version. Le nettoyage passe par des
patchs et le rendu par des items de texte : ni l'un ni l'autre ne remplace l'image de base
(principe non destructif déjà en place).

**Comment on navigue** : il n'existe **aucune interface ni raccourci** dédié. Les raccourcis
déclarés sont limités à `save_project`, `save_current_image`, `undo`, `redo`,
`delete_selected_box`, `restore_text_blocks`, `toggle_brush_strokes` (`app/shortcuts.py:16-59`).

**Persistance** : l'historique est bien **sauvé en entier** (pas seulement l'index)
(`project_state_v2.py:347-356`, `:326-336`, `:338-345`, index dans le manifeste `:391`).

**Au rechargement** (`project_state_v2.py:531-556`) : `image_data[page] = None` (chargement
paresseux) ; `in_memory_history[page][idx] = None` — **placeholders** ; `image_history[page][idx]`
= chemin paresseux vers `temp_dir/unique_images/<id>/<nom>`, matérialisé à la demande.

Défauts latents à connaître avant de s'appuyer sur ce mécanisme :
- `SetImageCommand.get_img` (`commands/image.py:105-111`) teste `if self.ct.in_memory_history.get(file_path, [])` — une liste `[None, None]` est vraie, donc il renverrait `None` après un rechargement de projet.
- `SetImageCommand.undo/redo` agit sur `image_files[curr_img_idx]` (`commands/image.py:35`, `:57`), la page affichée, et non sur le `file_path` reçu au constructeur.

---

## 4. Calques réels dans le viewer

Une seule `QGraphicsScene` (`image_viewer.py:33-37`), aucune notion de calque ni de groupe.
Couches effectives, par type d'item et par `Z` :

| Couche | Type d'objet | Z | Preuve |
|---|---|---|---|
| Image de base | `self.photo: QGraphicsPixmapItem` | 0 | `image_viewer.py:35-37`, `:343-352` |
| Tracés de pinceau / segmentation | `QGraphicsPathItem` | 0.8 | `drawing_manager.py:49` |
| Patchs de nettoyage | `QGraphicsPixmapItem` marqués par `data(0) = hash` | 0.5 | `commands/base.py:250-261` |
| Rectangles de blocs | `MoveableRectItem` | 1 | `rectangle.py:41`, `image_viewer.py:368-376` |
| Texte traduit | `TextBlockItem` | 1 | `text_item.py:106`, `image_viewer.py:378-442` |

**Aucune couche ne peut être masquée.** Aucun `setVisible` sur la photo, un patch, un rectangle
ou un item de texte dans `app/ui/canvas/` ; aucun bouton à bascule de visibilité dans
`app/ui/main_window/builders/*`.

**Il n'existe donc pas de « voir l'original »**. Les seuls équivalents sont destructifs ou
partiels : `clear_text_items()` (`interaction_manager.py:225`), `clear_rectangles()`
(`interaction_manager.py:217`), `Ctrl+Shift+R` (`controller.py:326-337`).

**Point structurant pour la suite** : la composition affichée et la composition exportée sont
produites par **deux chemins distincts**. L'export image reconstruit une scène neuve à partir de
`viewer_state['text_items_state']` et de `image_patches`
(`projects.py:914-924`, `save_renderer.py:8-67`, `:238-261`) ; l'export PSD de même
(`projects.py:932-975`). Une visibilité ajoutée côté viewer n'aurait **aucun** effet sur l'export
tant qu'elle n'est pas portée dans l'état.

---

## 5. Écart mesuré vs hypothèses E1-E4

| Hypothèse | Verdict | Preuve |
|---|---|---|
| **E1 — Panneau de calques + « voir l'original »** | **Absent** (les couches existent physiquement, la visibilité n'existe pas) | §4 |
| **E2 — Journal de page persisté** | **Quasi absent** : seul le rapport de lot est persisté, pages sautées uniquement | `batch_report.py:236-261` ; aucune clé d'horodatage par page (`image.py:64-91`) |
| **E3 — Versions de traduction par bloc** | **Absent** | `TextBlock.translation` scalaire (`textblock.py:47`), écrasé par 7 chemins (§1.3) |
| **E4 — Découvrabilité** | **Partiellement couvert** : le socle existe, il est peu visible | détail ci-dessous |

Détail E4 — ce qui existe mais ne se voit pas :
1. Champs source et traduction toujours affichés (`workspace.py:154-166`) mais vides sans sélection, vidés au changement de page (`image.py:1129`) et après le rendu (`text.py:929`).
2. Aucune étiquette : seules des infobulles sur les listes de langues.
3. Sauvegarde automatique **désactivée par défaut** (`projects.py:61-66`) ; interrupteur dans la barre de titre (`title_bar.py:692-700`), réglages dans Réglages > Projet (`project_page.py:26-30`).
4. Aucune invite à enregistrer le projet à l'ouverture d'un CBZ (`projects.py:214-228`).
5. « Reconnaître » sort en silence sans rectangle (`pipeline/ocr_handler.py:24`).
6. Le rendu efface les rectangles (`text.py:947`) ; `Ctrl+Shift+R` non signalé dans l'interface.
7. L'instantané de récupération n'est proposé que si aucune page n'est chargée (`projects.py:433-436`).

---

## 6. Points de branchement minimaux (constat, pas conception)

1. **Panneau latéral gauche** : `page_list` et `search_panel` s'excluent mutuellement (`workspace.py:95-108`, bascule `nav.py:207-221`, bouton `nav.py:162-167`). Précédent exact d'un panneau supplémentaire.
2. **Version de traduction par bloc** : (a) attribut supplémentaire sur `TextBlock`, sérialisé automatiquement (`parsers.py:57-63`, `:174-178`) — attention, `TextBlock.deep_copy` (`textblock.py:78-112`) recopie les champs un par un ; (b) clé supplémentaire dans `image_state` (`image.py:64-91`, les clés inconnues survivent, `:73`).
3. **Journal par page** : (b) ci-dessus, ou table SQLite supplémentaire dans `_init_schema` (`project_state_v2.py:45-107`) ; les tables inconnues sont ignorées à la lecture (`:702-735`).
4. **Versionnage de schéma** : `project_format_version = "2"` **écrite** (`:413-416`) mais **jamais lue**.
5. **Réaction aux clés inconnues** : manifeste et pages lus par `.get(...)` (`:493-509`, `:558-579`, `:595-614`) → ignorées ; `TextBlock` : `__dict__.update` → attributs inconnus restaurés ; tables inconnues ignorées ; **limites dures** : `msgpack.unpackb(..., strict_map_key=True)` (`:710`, `:712`, `:720`) — clés de dict non `str`/`bytes` → échec ; `ProjectEncoder.encode` renvoie l'objet inchangé s'il ne connaît pas son type (`parsers.py:23-29`) → `TypeError` à la sauvegarde pour tout type nouveau.
6. **Point de passage unique du nettoyage** : `InpaintingHandler.inpaint_image` (`pipeline/inpainting.py:651-682`, ADR-007).
7. **Point de passage unique des patchs** : `PatchInsertCommand` (création), `load_patch_state` (`image.py:984-1008`, réaffichage), `save_renderer.apply_patches` (export).
8. **Création des piles** en 4 endroits (`image.py:405-414`, `:460-464`, `:511-522`, `projects.py:1309-1314`) — à factoriser avant d'y toucher.

---

## 7. Mesures à faire (procédure)

7.1 Aller-retour `.ctpr` sur une page traitée (blocs, état de page, patchs, historique, pile).
7.2 Historique d'images : confirmer une seule entrée par chemin (manuel, lot, webtoon).
7.3 Nettoyage répété ×3 : patchs, taille du `.ctpr`, `Ctrl+Z`.
7.4 Retraduction : T1 perdue ? pile inchangée ? édition manuelle → +1 commande.
7.5 Poids du projet sur un album complet, par table.
7.6 Compatibilité ascendante : clés inconnues (fork → origine), fichier d'origine (origine → fork), fixture synthétique.
7.7 Aller-retour PSD.
7.8 Découvrabilité, chronométrée.
7.9 Piles d'annulation entre pages.

---

## 8. Mesures effectuées

### 8.1 Aller-retour `.ctpr` (2026-09-13, app hors écran, page `funhome_012`, mode manuel)

Séquence : Détecter → Reconnaître (English) → traduction posée à la main (`TRAD i v1`) →
Segment → Nettoyer → retraduction (`TRAD i v2`) → `save_state_to_proj_file_v2` → nouveau processus
→ `load_state_from_proj_file_v2`.

| Élément | Avant fermeture | Après réouverture | Verdict |
|---|---|---|---|
| Blocs (`blk_list` de l'état de page) | 10 | 10 | conservé |
| Texte source OCR (`blk.text`) | « MY FATHER COULD… » | identique | **conservé** |
| Traduction (`blk.translation`) | `TRAD i v2` | `TRAD i v2` | conservé ; **`v1` perdue** (§1.3 confirmé) |
| Champs `TextBlock` restaurés | 20 champs (`xyxy`, `text_class`, `bubble_xyxy`, `lines`, `texts`, `source_lang`, `target_lang`, `font_color`, `angle`, `tr_origin_point`, …) | identiques | conservé |
| Patchs de nettoyage | 6 | 6 (`bbox`, `hash`, PNG paresseux) | conservé, 247 Ko de blobs |
| Tracés de segmentation (`brush_strokes`) | 10 | 10 | conservé |
| Langues de page | English / French | English / French | conservé |
| Historique d'images | 1 entrée, index 0 | 1 entrée (`None` en mémoire, chemin paresseux), index 0 | **jamais plus d'une entrée** (§3 confirmé) |
| Pile Annuler/Rétablir | 4 commandes | **aucune pile** (groupe vide) | **perdue** (§1.4 confirmé) |
| Table `meta` | — | `project_format_version = 2` | écrite, jamais lue |

Poids : 728 Ko pour une page (image 362 Ko + 6 patchs 247 Ko + états). Le détail « rectangles et
items de texte du `viewer_state` » n'a pas pu être mesuré fidèlement hors écran (la capture de
l'état du viewer se fait au changement de page dans l'app réelle) : à refaire dans l'app.

### 8.2 Reste à mesurer (§7)
7.2 chemins lot/webtoon · 7.3 nettoyage répété (taille du fichier) · 7.4 retraduction et pile
(partiellement : 4 commandes après segment+nettoyage, aucune après pose de traduction) ·
7.5 album complet · 7.6 clés inconnues et fichier d'origine · 7.7 PSD · 7.8 découvrabilité ·
7.9 piles entre pages.
