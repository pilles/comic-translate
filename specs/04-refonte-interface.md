# Spec 04 — Refonte de l'interface et du parcours

> Suite du brief `specs/brief-refonte-interface.md`. Ce document tranche les questions ouvertes,
> décrit la cible et découpe le travail en jalons testables un par un.
> Maquette de référence : « Atelier de traduction BD » (artefact publié le 2026-09-21).

---

## 1. Décisions prises (2026-09-21)

| # | Question | Décision |
|---|---|---|
| 1 | Page par page ou album d'abord ? | **Ni l'un ni l'autre : une sélection.** Voir §2, la machinerie existe déjà. |
| 2 | Que voir en ouvrant une page traitée ? | **Le rendu final.** Les bulles restent cliquables, sans raccourci caché. |
| 3 | Réagencement ou nouvelle fenêtre ? | **Nouvelle fenêtre principale**, conforme à la maquette. |
| 4 | Mode revue dédié ? | **Oui**, page suivante / bulle suivante au clavier. Jalon tardif. |
| 5 | Place du lot ? | C'est le point 1. |

---

## 2. Ce que le code sait déjà faire (mesuré, pas supposé)

Le « lancer un test sur 5 pages » demandé au point 1 **est déjà implémenté** :

- `app/ui/list_view.py:241-247` — clic droit sur une sélection de pages, entrée « traduire ».
- `controller.py:249` — `page_list.translate_imgs` → `batch_translate_selected`.
- `controller.py:596-627` — `_run_batch_for_paths` : dédoublonnage, validation des réglages par
  page, lot restreint à la sélection (`selected_batch`, vide = album entier).
- `app/controllers/batch_report.py` — rapport de lot : pages sautées, raison localisée, action
  conseillée, bouton de reprise (`retry_skipped_batch_images`, `controller.py:609`).
- `controller.py:646-720` — annulation en cours de lot, barre de progression nommant la page
  courante, purge des modèles après lot, sauvegarde automatique du rapport.

**Conclusion : il n'y a rien à construire pour le point 1, il y a à le montrer.** Aujourd'hui,
la seule façon de découvrir cette fonction est un clic droit que rien n'annonce.

Autre acquis exploitable : `image_states[chemin]` est un dictionnaire par page déjà persisté dans
le projet, et `_build_image_state` (`app/controllers/image.py:74`) repart de l'état existant avant
de le mettre à jour — **les clés inconnues survivent**. Ajouter un état d'avancement par page ne
casse donc aucun `.ctpr`, dans aucun sens.

---

## 3. Le mode qui existe vraiment, et qu'il faut supprimer

Philippe demandait « savoir dans quel mode on navigue ». Un mode existe bel et bien, et c'est une
source de confusion :

- `controller.py:177` — deux boutons radio, `manual_radio` / `automatic_radio`.
- `controller.py:470-478` — « Automatique » **grise les six boutons d'étape** ;
  « Manuel » **grise « Traduire tout »**.

Autrement dit, la moitié des commandes est éteinte en permanence selon un réglage que rien
n'explique. **Cible : plus aucun mode.** Les étapes restent toujours disponibles ; le lot est
simplement « les pages sélectionnées ». L'intuition de Philippe — « c'est peut-être pas tout à fait
utile » — est la bonne : ce qui manquait n'était pas un indicateur de mode, c'était la disparition
du mode.

---

## 4. La cible

Une fenêtre, quatre zones, aucune superposition de sujets.

**Barre de titre** — nom du projet, état de sauvegarde en clair (« enregistré il y a 2 min »),
jamais un simple interrupteur muet.

**Colonne de gauche — les pages.** Vignette, numéro, et une **piste d'avancement en cinq segments**
(détectée, reconnue, traduite, nettoyée, rendue). Sélection multiple, et un bouton visible
« Traduire la sélection » sous la liste, qui remplace le clic droit caché. C'est là que se joue le
test sur 5 pages : on sélectionne 5 pages, on lance, on juge, on continue ou on change les réglages.

**Centre — la page.** Rendu final par défaut (décision 2), bulles cliquables sans raccourci. Le
bouton « Original » et la touche Alt (jalon B, ADR-013) restent tels quels.

**Barre d'étapes flottante** — les six étapes affichées comme un avancement, avec **une seule
action principale** (« Continuer ») qui lance l'étape suivante de la page courante. Chaque étape
reste cliquable individuellement pour reprendre la main.

**Panneau de droite — contextuel.** Bulle sélectionnée → source anglaise étiquetée et jamais vidée,
traduction, bouton **« Historique »** nommé (plus l'icône ambiguë), police et rendu. Rien de
sélectionné → réglages de la page. Les outils de dessin et de nettoyage sortent du panneau texte
pour rejoindre une barre d'outils.

**Retours explicites partout** : « 10 bulles reconnues, 1 sans texte », « aucun bloc détecté sur
cette page », « modèle indisponible ». Plus jamais de silence après une action.

---

## 5. Jalons

Chaque jalon se termine par un test manuel que Philippe fait lui-même, et un commit.

### Jalon 1 — État d'avancement par page

*But :* savoir où on en est, sur une page comme sur 242. C'est le socle de tout le reste, et il est
visible immédiatement dans l'interface actuelle.

- Nouveau module `modules/pagestate/` : énumération des cinq étapes, calcul de l'état d'une page à
  partir de son `image_states` et de son `blk_list` (pas de nouvelle source de vérité).
- **Déduction pure, aucune écriture** : contrairement à ce que ce paragraphe prévoyait à l'origine
  (« écriture de l'état au passage de chaque étape », « persistance : clé supplémentaire dans
  `image_states` »), l'implémentation ne persiste rien — deux statuts par étape (FAITE / ABSENTE),
  recalculés à l'affichage sur `blk_list` (page vivante) ou `image_states` (autre page). Décision et
  option B rejetée : ADR-014 (`specs/decisions.md`).
- Affichage : pastilles (piste de cinq segments) dans la liste de pages existante, par composition
  autour du délégué amont.

*Critère de réussite :* ouvrir un CBZ, traiter deux pages différemment, fermer, rouvrir le projet —
les pastilles reflètent exactement ce qui a été fait. Aucun ancien `.ctpr` ne refuse de s'ouvrir.

> **Livré le 2026-09-22.** Fichiers : `modules/pagestate/{__init__,progress,collect,ui}.py`
> (nouveau paquet), `controller.py` (2 lignes `# fork:`), `tests/conftest.py` (1 ligne `# fork:`).
> 3 lignes amont, 2 fichiers touchés. Tests : `tests/test_pagestate.py` (27, hors GUI),
> `tests/test_pagestate_ui.py` (15, `--gui`). `uv run pytest -q` → 240 passed ; `--gui` → 287
> passed, 3 skipped, 1 failed (`test_app.py`, échec amont connu). Non-écriture prouvée par SHA-256
> identique d'un `.ctpr` avant/après une rafale de peintures. Détail complet, limites et défauts
> amont découverts : ADR-014.
>
> **Protocole de test manuel (Philippe)** :
> 1. Ouvrir le CBZ de test, page 11 : Détecter, Reconnaître, Traduire, Segmenter + Nettoyer, Rendre.
>    Après chaque étape, la pastille correspondante se remplit en moins d'une seconde, sans changer
>    de page.
> 2. Page 12 : seulement Détecter et Reconnaître → 2 pastilles pleines, 3 éteintes.
> 3. Page 11 : Cmd+Z sur le nettoyage → 4e pastille éteinte ; Cmd+Shift+Z → rallumée.
> 4. Taper du texte dans le champ traduction d'une bulle qui n'en avait pas → « traduite » s'allume ;
>    tout effacer → elle s'éteint.
> 5. Sélectionner les pages 13 à 15, clic droit → Translate : les pages passent à 5/5 une à une. **Ne
>    pas changer de page pendant le lot** (défaut amont n°1, ADR-014).
> 6. Lancer un lot sur 16 à 20 et l'annuler au milieu : chaque page ouverte montre exactement ce que
>    ses pastilles annonçaient.
> 7. Marquer la page 12 « Skip » : nom barré et piste atténuée, lisible.
> 8. Survoler une page : infobulle « Détectée (N blocs) · Reconnue x/N · … », lisible ; sur une page
>    jamais traitée, « Pas encore détectée »…
> 9. Enregistrer, quitter, rouvrir le `.ctpr` : pastilles identiques, pas de clignotement « tout
>    vide » sur la page affichée, défilement fluide.
> 10. Ouvrir un `.ctpr` enregistré avant ce jalon : il s'ouvre, pastilles fidèles à son contenu.
> 11. Thème clair et thème sombre du système : pastilles lisibles dans les deux, y compris sur la
>     ligne sélectionnée.
> 12. Une minute sans rien faire : CPU au repos inchangé dans le Moniteur d'activité.

### Jalon 2 — La nouvelle fenêtre

*But :* la coquille de la maquette, sans aucune fonction nouvelle.

- Nouveaux constructeurs d'interface à côté de l'existant, réutilisant **les widgets et les
  contrôleurs actuels sans les réécrire** (`ImageViewer`, contrôleurs `app/controllers/`).
  C'est la condition pour que le coût de rebase reste supportable.
- Panneau de droite contextuel, barre d'outils séparée, champs texte redimensionnables
  (fin du 120 px en dur, défaut 10 de la table du brief).
- Suppression des boutons radio Manuel / Automatique (§3).

*Critère de réussite :* tout ce qui marchait marche encore — détection, OCR, traduction, nettoyage,
rendu, historique par bulle, bouton Original, exports image/CBZ/PDF/PSD, ouverture et sauvegarde de
projet. Rien de neuf, rien de cassé.

> **Découpage** : le jalon 2 est livré en quatre sous-étapes.
>
> **2a — nouvelle disposition, livrée le 2026-09-27.** `modules/shell/` (nouveau paquet) reparente
> les mêmes objets construits par `_create_main_content` (jamais recréés) dans une disposition à 3
> colonnes : pages + recherche à gauche, page + badge Original en surimpression au centre, panneau
> droit (Source/Traduction, Historique, Rendu du texte, Outils) à droite. Amont touché :
> `app/ui/main_window/window.py` (2 lignes `# fork:`), `tests/conftest.py` (1 ligne) — zéro ligne
> dans `workspace.py`/`nav.py`/`controller.py`/les contrôleurs/`pipeline/`. Interrupteur
> `COMIC_SHELL=0` pour revenir à l'ancienne disposition sans bandeau (diagnostic). Détail complet :
> ADR-015 (`specs/decisions.md`).
> Mesures : champs texte 136/135 px à 1225×797 (contre 120 px fixes avant), 84/83 px à 1066×693
> (« Texte plus grand » — sous les 120 px d'avant, voir 2c). Tests : `tests/test_shell.py` (7, hors
> GUI), `tests/test_shell_ui.py` (30, `--gui`).
> Maquette versionnée : `specs/maquette-atelier.html`.
>
> Reste à faire : **2b** (radios et interrupteur webtoon parqués cachés, Cancel grisé au repos et
> actif seulement pendant un lot), **2b-bis** (issue au défaut amont n°3 de l'ADR-014 —
> `task_runner.py`, ne jamais se déclencher pendant l'exécution d'un lot ; **décision de Philippe
> en attente**), **2c** (pile Page/Bulle, règle de focus lue sur `window().focusWidget()`).
> « Source jamais vidée » (annotation 4 de la maquette) : **reporté**.
>
> **Note** : un hotfix sans rapport avec le jalon 2 a été livré le même jour (analyse du texte de
> la page sur l'image d'origine plutôt que sur l'image nettoyée, ADR-016) — il supprimait un piège
> qui gênait tous les tests manuels de la nouvelle disposition (blocs remplacés par zéro après un
> cycle Détecter/Nettoyer/Détecter).
>
> **2b livrée le 2026-09-27.** `manual_radio`/`automatic_radio`/`webtoon_toggle` passés en zone
> `PARKED` (`modules/shell/manifest.py`), masqués sur place (`_hide_parked_widgets`, y compris en
> repli) plutôt que déplacés ; sous `COMIC_SHELL=0`, seul `webtoon_toggle` est masqué. `controller.py`
> (6 lignes `# fork:`) : `batch_mode_selected`/`manual_mode_selected` rendent le même état de repos
> quel que soit `main_page/mode` ; étapes grisées pendant un lot, réactivées et Cancel regrisé à la
> fin. `app/controllers/projects.py` (1 ligne `# fork:`) : `webtoon_mode = False` forcé au chargement
> d'un projet. ~19 tests ajoutés à `tests/test_shell_ui.py`. Suites : 248 passed hors GUI ; `--gui`
> 346 passed, 3 skipped, 1 failed (`test_app.py`, amont connu). Détail : ADR-015 (amendement),
> `specs/decisions.md`.
>
> **2b-bis : livrée le 2026-09-27** (ADR-019 : `task_runner.py`, 10 lignes `# fork:`, 7 tests hors GUI).
> Historique de la décision : Philippe a tranché le 2026-09-27 : corriger le
> défaut amont n°3 (ADR-014, `_batch_active` bloqué à `True`) par 3 lignes dans `task_runner.py`,
> garde-fou « ne jamais se déclencher pendant l'exécution d'un lot », comparaison du rappel par
> `==`. (Livré avec 10 lignes au lieu de 3 : mémorisation de l'opération en cours nécessaire au garde-fou.)
>
> **2c livrée le 2026-09-28.** Panneau de droite contextuel : `panel.py` réécrit en
> `QStackedWidget` à deux pages — Page (rien de sélectionné : Langue source/cible, `set_all_button`,
> aide « Sélectionnez une bulle pour voir son texte ») et Bulle (une bulle sélectionnée : `QSplitter`
> vertical « <langue> · reconnu » + « <langue> · traduction », bouton Historique). « Rendu du
> texte »/« Outils » restent communs sous la pile. `modules/shell/context.py` (pur, `panel_context`)
> + `modules/shell/watcher.py` (nouveau, `_ContextWatcher`) basculent la pile sur signaux
> (`rectangle_selected`, `clear_text_edits`, `currentItemChanged`, relâchement souris, Show/Hide de
> la recherche) regroupés par `singleShot(0)`, plus un chien de garde à 200 ms (médiane 0,0023
> ms/tick) pour les affectations directes sans signal. Règle de focus : lecture de
> `window().focusWidget()` (jamais `QApplication.focusWidget()`) avant tout `setCurrentIndex`,
> section sortante rendue au viewer ou déclarée sans focus, jamais de focus donné à la section
> entrante. Zéro ligne amont. Champs texte 161/160 px à 1225×797. Tests : `tests/test_shell.py` 15
> hors GUI, `tests/test_shell_ui.py` ~75 `--gui`. Suites : 263 passed hors GUI ; `--gui` 385 passed,
> 3 skipped, 1 failed (`test_app.py`, amont connu). Détail complet : ADR-015 (amendement,
> `specs/decisions.md`).
>
> **Jalon 2 clos** : 2a, 2b, 2b-bis, 2c livrées ; validation manuelle de Philippe reçue pour 2b et 2c
> le 2026-09-28 (couvre aussi 2a, déjà validée). Reporté : « source jamais vidée » (annotation 4 de
> la maquette).
>
> **Plantage natif rencontré pendant les tests de la 2b** (sans rapport avec le shell) : voir
> ADR-018 — bug PySide6/Shiboken6 6.11.2, pas du fork ; consigne de lancement des tests `--gui`
> mise à jour dans `CLAUDE.md`.

### Jalon 3 — Action unique et retours explicites

*But :* ne plus avoir à connaître l'ordre des étapes, ne plus subir le silence.

> **Sous-étape 3a — Réinitialiser la page.** Demande de Philippe (2026-09-28) : « rajoute un
> bouton "reset", ça permet de repartir sur une page "propre" ». Placée avant le reste du jalon 3
> (gain rapide). Cadrage ci-dessous, présenté comme des **choix par défaut à confirmer par la
> conception**, pas encore implémenté :
>
> - **Effet** : remettre la page courante dans l'état « jamais traitée » — aucun bloc, aucun
>   rectangle, aucun texte reconnu/traduit, aucun patch de nettoyage, aucun tracé de pinceau/
>   segmentation, aucun texte rendu — l'image d'origine seule, comme à l'ouverture de l'album. Les
>   pastilles du jalon 1 retombent à « rien de fait ».
> - **Annulable** par Cmd+Z en une seule étape (macro d'annulation) : c'est ce qui rend l'action
>   sûre sans boîte de confirmation. Si la conception montre qu'une annulation complète n'est pas
>   atteignable proprement, une confirmation explicite devient alors obligatoire.
> - **Portée** : la page affichée. Si plusieurs pages sont sélectionnées dans la liste : question
>   ouverte (appliquer à la sélection ou non), à trancher en conception.
> - **Ne touche jamais** : le fichier image d'origine, les autres pages, les réglages (langues,
>   police), le projet sur disque avant la prochaine sauvegarde.
> - **Historique par bulle** (ADR-012) : les versions disparaissent avec les blocs ; l'annulation
>   les restaure.
> - **Emplacement du bouton** : dans l'en-tête, à côté des six étapes (libellé « Réinitialiser ») —
>   à confirmer en conception au regard de la barre d'étapes du jalon 3.
> - **Critère de réussite manuel** : sur une page traduite, rendue et nettoyée → Réinitialiser →
>   page d'origine, panneau vide, pastilles éteintes ; Cmd+Z → tout revient ; Détecter repart
>   normalement.
>
> **3a livrée le 2026-09-28, validée à la main par Philippe.** Mécanisme retenu : option C
> améliorée (`ResetPageCommand` réécrit les clés traitées d'`image_states[p]`/`image_patches[p]`
> puis recharge par `image_ctrl.load_image_state(p)`, identité de la liste de blocs préservée) —
> l'option B (détacher/rattacher les items Qt vivants) a été abandonnée après revue du critic
> (câblage des signaux trop tôt, macro évaluée à l'index 0). Bouton « Réinitialiser » dans l'en-tête
> (`modules/reset/`, `MPushButton`), actif ssi étapes actives, file de tâches vide, pas de lot, pas
> webtoon, pile d'annulation = pile de la page affichée. Caches OCR/traduction invalidés (décision de
> Philippe : Traduire rappelle vraiment Ollama après reset) ; portée = page affichée seule ; macro
> d'annulation orpheline détectée à l'ouverture → confirmation explicite (« non annulable ») au lieu
> d'un push silencieux. Amont : `controller.py` (2 lignes `# fork:`), `tests/conftest.py` (1 ligne).
> Tests : `tests/test_reset.py` (56, hors GUI), `tests/test_reset_ui.py` (46, `--gui`). Suites :
> 319 passed hors GUI ; `--gui` 487 passed, 3 skipped, 1 failed (`test_app.py`, amont connu). Détail
> complet, limites (MAJ1 notamment) et alternatives rejetées : ADR-020 (`specs/decisions.md`).
>
> **3a-bis (décidée par Philippe le 2026-09-28, à venir)** : corriger la macro d'annulation
> orpheline — défaut amont préexistant, indépendant du reset : la macro « inpaint »
> (`manual_workflow.py:605`) n'est fermée qu'au succès (`pipeline/inpainting.py:815`), idem pour la
> segmentation ; `endMacro` vise `activeStack()` à la fin de l'opération, donc une autre page si
> l'utilisateur a navigué entre-temps → toute commande suivante sur cette pile tombe dans une macro
> jamais fermée et Annuler est refusé jusqu'à la fermeture de l'app. Détail : ADR-020.
>
> **3a-ter (décidée par Philippe le 2026-09-28, à venir)** : rendre les annulations de texte
> robustes aux items recréés (MAJ1 de l'ADR-020) — `TextEditCommand`, `RestoreVersionCommand`,
> `TextFormatCommand` visent un item détruit après navigation ou reset et lèvent `RuntimeError` à
> l'annulation. Corriger ce défaut réglera aussi le cas général « changer de page puis revenir ».

- Barre d'étapes alimentée par le jalon 1, bouton « Continuer ».
- Messages de résultat après chaque étape, avec des nombres.
- Les échecs silencieux connus deviennent visibles : aucun rectangle avant « Reconnaître »
  (`pipeline/ocr_handler.py:24`), modèle injoignable, page sans bloc détecté.
- Reprise du signal « lancée sans résultat » (option B écartée au jalon 1, ADR-014) sous forme de
  message à la complétion d'une étape, pas d'un troisième statut persisté.

*Critère de réussite :* traiter une page entière sans jamais cliquer ailleurs que sur
« Continuer » ; provoquer une panne (endpoint Ollama éteint) et lire un message qui dit quoi faire.

### Jalon 4 — Le lot rendu visible

*But :* exposer ce qui existe déjà (§2).

- Bouton « Traduire la sélection » sous la liste de pages, avec le compte
  (« Traduire les 5 pages sélectionnées »).
- Progression par page et annulation visibles, rapport de fin lisible avec reprise des pages
  sautées.
- Vérification du comportement sur sélection partielle et sur album entier.
- Traiter le défaut amont n°4 relevé au jalon 1 (ADR-014) : perte du rendu de lot sur une page
  insérée (`viewer_state = {}`, `KeyError` sur `state['rectangles']` au chargement suivant).

*Critère de réussite :* sélectionner 5 pages, lancer, annuler au milieu, relancer, lire le rapport.

### Jalon 5 — Premier lancement et mode revue

*But :* les frictions de départ et la correction rapide d'un album.

- À l'ouverture d'un CBZ : proposer d'enregistrer le projet, activer la sauvegarde automatique par
  défaut, demander la langue source une fois (et retenir qu'« English » vaut mieux qu'« Auto »,
  défaut 10 du brief).
- Mode revue : page suivante / bulle suivante au clavier, sans quitter le panneau de correction.

*Critère de réussite :* ouvrir un CBZ neuf et arriver à une page traduite sans passer par les
réglages ; parcourir 10 pages et corriger 3 bulles sans toucher la souris.

---

## 6. Contraintes reprises du brief (non négociables)

1. Fork : toute ligne modifiée dans un fichier amont porte `# fork:` et reste minimale. Le code
   nouveau va dans des modules nouveaux. **La nouvelle fenêtre doit être un module nouveau qui
   réutilise l'existant, pas une réécriture des contrôleurs.**
2. PySide6 / Qt Widgets. Pas de QML, pas de web.
3. Compatibilité `.ctpr` dans les deux sens, export PSD inchangé, aucun appel réseau hors
   HuggingFace et l'endpoint Ollama configuré.
4. Aucun compte, aucune télémétrie.
5. Un jalon, un test manuel, un commit.

---

## 7. Reste ouvert

- ~~Mode webtoon~~ — **tranché le 2026-09-25 par Philippe : le fork abandonne le webtoon.** La
  nouvelle fenêtre ne le propose pas (aucun interrupteur, aucun chemin d'accès). Le code amont
  webtoon n'est **pas supprimé** (diff amont minimal, rebase) : il reste en place, inaccessible
  depuis l'interface du fork.
- L'historique par bulle (jalon A de la spec 03) ne couvre pas le traitement par lot. À décider au
  jalon 4 : enregistre-t-on une version par bulle pendant un lot de 242 pages, ou seulement en
  manuel ?
- Le nombre de pages par défaut d'un « lot d'essai » (5 ? 10 ?) n'a pas besoin d'être codé : c'est
  une sélection libre dans la liste.
