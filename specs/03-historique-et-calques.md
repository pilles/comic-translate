# Spec 03 — Historique de page et calques dans l'app

> **STATUT : jalon B (E1, voir l'original) implémenté le 2026-09-19, voir ADR-013
> (`specs/decisions.md`) et §9 ci-dessous. Test manuel de Philippe en attente.**
> **STATUT : jalon A (E3, versions par bloc) implémenté le 2026-09-16, voir ADR-012
> (`specs/decisions.md`) et §8 ci-dessous. Test manuel de Philippe en attente.**
> **STATUT : inventaire réalisé le 2026-09-13, voir `specs/03-inventaire.md`. Arbitrage E1-E4
> en attente de Philippe.**
> **STATUT initial : rédigée le 2026-09-11, à valider par Philippe.**
> **Conception d'abord** : l'architect produit l'inventaire (§2) et la conception (§4) ;
> **aucune ligne de code de production** avant validation de Philippe sur l'écart (§3).
> Prérequis : spec 01. Lire `00-feuille-de-route.md` §2 (ce qui existe) et §6.

**Objectif** : pouvoir **revenir sur une page plus tard**, voir **ce qui a été fait** et
**comparer / masquer** chaque couche (original, nettoyage, texte) sans quitter l'app.

**Besoins exprimés par Philippe (2026-09-11)** :
1. « On modifie, mais on ne peut pas revenir plus tard pour reprendre le travail. »
2. « Je ne retrouve plus le texte original après la traduction. »
3. « Un système de calques comme Photoshop, ce serait chouette. »
4. Garder un historique de la page et de ce qu'on y a fait.

**Retour de Philippe (2026-09-13)** :
- « Il manque quelque chose qui permette de se tromper et de revenir en arrière pour corriger. »
- « Interface simple mais pas pauvre. »
- « Tester à chaque grande modif. »
- « Correct sans être irréprochable. »

---

> **Découvrabilité OCR (E4)** — relevé le 2026-09-13 pendant le hotfix locale (JOURNAL.md,
> ADR-009). Deux défauts distincts de l'historique/calques mais de la même famille (l'app fait le
> travail sans le montrer) :
> 1. « Reconnaître » sort en silence s'il n'y a aucun rectangle sur la page
>    (`pipeline/ocr_handler.py:24`, aucun message affiché).
> 2. Le résultat OCR n'est visible que dans le champ source, après sélection du bloc concerné —
>    rien à l'écran tant qu'aucun bloc n'est sélectionné.
>
> Au passage : la langue source « Auto » colle les lignes de texte reconnu sans espaces
> (« WHEN WESPOTTED ONE,SHE… ») là où choisir « English » donne un texte propre — pas un défaut de
> découvrabilité, mais un piège d'usage relevé à la même occasion.

## 1. Point de départ : une partie existe déjà

Vérifié dans le code (spec 00 §2) : projets `.ctpr` avec sauvegarde auto et récupération, texte
source conservé par bloc, historique d'images, patchs de nettoyage, export et import PSD en
3 groupes. **Les besoins 1 et 2 sont probablement couverts** ; le problème peut être de
découvrabilité. Le lot doit le **prouver** avant de construire.

## 2. Inventaire exigé de l'architect (lecture seule)

Sur une page réelle traduite puis sauvegardée en `.ctpr`, fermée, rouverte :

| Question | Réponse attendue, mesurée |
|---|---|
| Que contient le `.ctpr` ? | schéma réel de `project_state_v2` (clés par page, format des patchs, historique) |
| Le texte original de chaque bloc est-il rechargé ? | oui / non, et où il s'affiche |
| La traduction précédente d'un bloc est-elle conservée après retraduction ? | oui / non |
| La pile Annuler/Rétablir survit-elle à la réouverture ? | oui / non (hypothèse : non) |
| Que devient une page nettoyée puis re-nettoyée ? | patchs empilés ou remplacés |
| Quels réglages de traitement sont mémorisés par page ? | modèle, contexte, inpainter : oui / non |
| Aller-retour PSD : export → retouche → import | ce qui est conservé, ce qui est perdu |

Livrable : `specs/03-inventaire.md`, faits datés, sans extrapolation. Réponses détaillées : tableau
§1 de `specs/03-inventaire.md`.

## 3. Écart attendu — à confirmer par l'inventaire

Hypothèses de manques, **à valider ou réfuter** :

- **E1 — Panneau de calques dans l'app** : visibilité par couche — image originale, patchs de
  nettoyage, texte traduit, et **texte original en surimpression**. Plus une touche maintenue
  « voir l'original » pour comparer instantanément.
  Inventaire : **absent** — couches physiquement distinctes mais aucune visibilité par couche,
  aucune touche « voir l'original » (`03-inventaire.md` §4, verdict §5).
  **Couvert partiellement (jalon B, 2026-09-19)** — bascule bouton + touche Alt maintenue voir
  §9 ci-dessous et ADR-013 ; visibilité par couche (calque de nettoyage isolé, par exemple) non
  couverte.
- **E2 — Journal de page persisté** : liste horodatée des opérations (détection, OCR, traduction
  avec modèle et contexte utilisés, nettoyage avec méthode, éditions manuelles), sauvegardée dans
  le `.ctpr`, consultable dans un panneau.
  Inventaire : **quasi absent** — seul le rapport de lot est persisté (pages sautées et motif
  uniquement, ni modèle ni réglage ni opération réussie) (`03-inventaire.md` §1.6, verdict §5).
- **E3 — Versions de traduction par bloc** : chaque retraduction ou édition crée une version ;
  restaurer une version antérieure en un clic.
  Inventaire : **absent** — `TextBlock.translation` est un champ scalaire unique, écrasé en place
  par 7 chemins (`03-inventaire.md` §1.3, verdict §5, mesure §8.1).
  **Couvert (jalon A, 2026-09-16)** — voir §8 ci-dessous et ADR-012.
- **E4 — Découvrabilité** : si l'inventaire montre que 1 et 2 sont couverts, les rendre visibles
  (proposition d'enregistrer le projet à l'ouverture d'un CBZ, champ source toujours affiché).
  Inventaire : **partiellement couvert** — le socle (texte source, historique, patchs) existe et
  survit à la réouverture, mais reste peu visible : champs vidés au changement de page et après
  rendu, aucune étiquette, sauvegarde auto désactivée par défaut (`03-inventaire.md` §5 détail E4).

Philippe arbitre la liste retenue **après** l'inventaire. Ordre de priorité proposé :
E4 → E1 → E3 → E2.

**Ordre retenu après le jalon A (2026-09-16)** : jalon A = E3 (versions par bloc, fait, §8) →
jalon B = voir l'original (E1, fait le 2026-09-19, §9) → **jalon C** = pile persistée (E2,
journal de page persisté au sens plein, au-delà du seul journal de versions du jalon A) →
**jalon D** = découvrabilité (E4, mise en visibilité de ce qui existe déjà : étiquettes,
sauvegarde auto, invite à l'ouverture d'un CBZ). Prochain jalon : **C**.

## 4. Contraintes de conception

1. **Compatibilité ascendante** : un `.ctpr` créé par l'app d'origine s'ouvre dans le fork ; le
   fork écrit un schéma **versionné** (ajout de clés, jamais de changement de sens d'une clé
   existante). Ouvrir un projet du fork dans l'app d'origine : dégradation acceptée mais **sans
   plantage**, à vérifier.
2. **L'export PSD ne régresse pas** : mêmes groupes, même ordre.
3. **Non destructif** : aucune opération n'écrase l'image originale ; les couches sont des
   données séparées, recomposées à l'affichage et à l'export.
4. **Taille du projet** : mesurer le poids du `.ctpr` sur un album complet avant/après E2 et E3 ;
   plafond à proposer par l'architect d'après la mesure.
5. Code nouveau dans des modules nouveaux (`app/layers/`, `app/history/` ou équivalent) ;
   points de branchement dans le code d'origine minimaux, marqués `# fork:`.

## 5. Tests

- Aller-retour de sauvegarde : page traitée → `.ctpr` → réouverture → état identique
  (blocs, texte source, traduction, versions, journal).
- Ouverture d'un `.ctpr` d'origine (fixture générée par la version de base du fork).
- Visibilité des calques : composition affichée = composition exportée.

## 6. Critère de réussite

1. Philippe traduit une page, ferme l'app, la rouvre le lendemain : il retrouve la page, le texte
   original et la traduction de chaque bulle, et l'historique de ce qui a été fait.
2. Il masque le texte traduit d'un clic et voit l'original de la bulle.
3. Il restaure une traduction antérieure d'une bulle.

## 7. Ce qui n'est pas fait

- Édition de calques de dessin (pinceau, retouche d'image) au-delà de l'existant.
- Synchronisation ou sauvegarde distante des projets.
- Cœur headless, MCP, chat (specs 04 à 06).

## 8. Jalon A — versions par bloc (2026-09-16)

Chaîne : architect → critic pass 1 (« Architect must revise », 5 bloquants B1-B5) → conception v2
→ critic pass 2 (« Acceptable to proceed », 5 majeurs traités en consignes) → implementer →
**tester en cours**. Détail complet, alternatives rejetées et défauts connus : ADR-012
(`specs/decisions.md`).

### Ce qui est construit

- Paquet `modules/history/` : `versions.py` (module pur, sans Qt — `set_text`, `snapshot`/
  `record_diff`, `flush_pending`, `versions_of`, `prune`), `commands.py`
  (`RestoreVersionCommand`), `ui.py` (bouton « Historique du bloc » + menu, dans
  `t_combo_text_layout`, à droite du champ traduction).
- Attribut `versions` paresseux sur `TextBlock` (jamais déclaré dans `__init__`), sérialisé
  automatiquement par `__dict__` — aucun encodeur dédié.
- Enregistrement à l'**affectation** sur le bloc vivant (6 sites, pas dans les processeurs qui
  travaillent parfois sur des copies jetables) : `ocr_handler.py:46/:80`,
  `translation_handler.py:56/:87`, `cache_manager.py:339/:346` ; plus le diff dans
  `OCRProcessor.process` et `Translator.translate` (seul endroit où le nom du moteur est
  disponible pour `meta`).
- **Règle du pré-état** : avant d'écraser un champ, la valeur qu'il portait est poussée dans le
  journal si elle divergeait de la tête — `manual` si le champ avait déjà une entrée, `prior`
  sinon (décision par champ, pas par bloc).
- `flush_pending` appelé dans `save_image_state` (changement de page, sauvegarde manuelle/auto,
  exports) : rattrape les écritures directes (frappe dans les champs) et c'est le seul point qui
  élague le journal (fil GUI uniquement).
- Dédoublonnage et marqueur « entrée courante » par `casefold()` (la mise en casse s'applique
  après chaque traduction, pas seulement au rendu).
- Plafonds : 12 entrées/champ, 2 000 caractères/valeur, 6 000 caractères/bloc ; la plus ancienne
  entrée de chaque champ est épinglée.
- Restauration annulable : `Ctrl+Z` après une restauration retire l'entrée `restore` (jamais le
  pré-état) ; `_commit_pending_text_command()` appelé d'abord ; `blockSignals` sur les deux champs
  pour restaurer une valeur de source sans réécrire la traduction (ou l'inverse).
- 8 fichiers amont touchés, 29 lignes `# fork:` (`textblock.py` 2, `ocr/processor.py` 7,
  `translation/processor.py` 7, `ocr_handler.py` 3, `translation_handler.py` 3,
  `cache_manager.py` 3, `image.py` 2, `workspace.py` 2). `search_replace.py`, `text.py`,
  `commands/base.py`, `project_state_v2.py` **non touchés**.

### Limites (voir ADR-012 pour le détail)

- Le **lot** (`batch_processor.py:441-443`) remplace `blk_list` entier pour la page : journal
  perdu pour les blocs remplacés. Pas de couverture au jalon A (idée en réserve : report
  positionnel par IoU, `specs/00-feuille-de-route.md` §5).
- Le **webtoon** n'est pas couvert (ni flush, ni pré-état sur ses écritures directes).
- **Rechercher/Remplacer** n'est pas instrumenté ; rattrapé par le pré-état au flush suivant,
  étiqueté `manual`.
- Au-delà de 2 000 caractères, un champ n'a plus d'historique (champ écrit quand même).
- Une correction qui ne change **que la casse** n'est jamais journalisée.
- La borne de volumétrie n'est garantie qu'après le flush de la page courante.
- Journal partagé possible entre un bloc supprimé encore référencé et son bloc recréé par
  annulation (aliasing amont préexistant, non corrigé).

### Point de test manuel de Philippe

Page `funhome_012`, mode manuel, langue source English.

1. Detect → Reconnaître → Traduire.
2. Corriger une bulle à la main dans le champ de droite (traduction).
3. Changer de page puis revenir (déclenche le flush).
4. Bouton **Historique** (icône à droite du champ traduction) : **3 entrées** attendues — OCR,
   traduction, correction manuelle.
5. Vider la traduction de cette bulle et « Traduire » le bloc seul via le menu contextuel du
   rectangle (chemin bloc unique, sert le cache) : **4e entrée** (cache) ; la correction
   manuelle reste restaurable dans le menu.
6. Cliquer sur l'entrée de la correction manuelle pour la restaurer.
7. `Ctrl+S` → fermer l'app → rouvrir → l'historique et la valeur restaurée sont présents.

> Contre-épreuve « projet antérieur » automatisée : `COMIC_TRANSLATE_LEGACY_CTPR=<chemin d'un .ctpr créé avant le jalon> QT_QPA_PLATFORM=offscreen uv run pytest --gui tests/test_legacy_ctpr_compat.py` (3 tests, sautés sans la variable ; le fichier contient une page de BD, jamais commité).

**Contre-épreuves** :
- `Ctrl+Z` juste après la restauration : la valeur précédente revient, la liste d'historique est
  inchangée (l'entrée `restore` disparaît, pas le pré-état).
- Ouvrir un projet `.ctpr` antérieur au jalon A : menu d'historique vide au départ ; la première
  retraduction crée une entrée `prior` puis une entrée `translation`.

## 9. Jalon B — voir l'original (2026-09-19)

Chaîne : architect → critic pass 1 (« Architect must revise », touche de composition clavier Mac
français en conflit avec la saisie, voile « collé » en cas de relâchement manqué, clics avalés) →
conception v2 → critic pass 2 (« Acceptable to proceed », 2 consignes bloquantes) → implementer.
Détail complet, alternatives rejetées et limites : ADR-013 (`specs/decisions.md`).

### Ce qui est construit

- `modules/view/original.py` (nouveau paquet, importe PySide6) : `OriginalViewImageViewer`,
  sous-classe d'`ImageViewer` qui peint le voile dans `drawForeground` — fond opaque puis la photo
  d'origine par-dessus tous les items de la scène. **Rien n'est modifié dans la scène** :
  `scene.render()` (export image/CBZ/PDF/PSD, « enregistrer l'image courante » Cmd+E) ignore le
  voile par construction, mesuré ; OCR/détection/traduction/nettoyage y sont insensibles ; aucune
  levée temporaire nulle part.
- Deux déclencheurs combinés (`_veil_active`) : bouton **Original** (checkable, colonne Outils à
  côté de Pan, hors outils exclusifs, s'enfonce pendant Alt) et touche **Alt/Option** maintenue.

  Règles d'armement de la touche Alt :

  | Condition | Effet si non remplie |
  |---|---|
  | Espace de travail actif | Alt sans effet |
  | Aucune fenêtre modale ouverte | Alt sans effet |
  | Fenêtre principale active | Alt sans effet |
  | Aucune saisie en cours (champ éditable focalisé ou bulle en édition sur le canevas) | Alt sans effet |
  | Pas en mode webtoon | Alt sans effet, bouton grisé |

  Désarmement sur relâchement d'Alt, désactivation de la fenêtre, changement d'état applicatif, et
  resynchronisation sur l'état réel du clavier au premier événement suivant (rattrape un
  relâchement manqué par l'app — feuille native, changement d'app).
- Aucun clic avalé : les éléments de la scène restent cliquables sous le voile (dit dans
  l'infobulle du bouton).
- Webtoon : voile jamais peint (garde indépendante de l'état du bouton), bouton grisé.
- Rien n'est persisté (`.ctpr`, QSettings) — état de vue pure.
- 5 lignes `# fork:` (`window.py` 2, `workspace.py` 2, `tests/conftest.py` 1).

### Limites (voir ADR-013 pour le détail)

- Voile tout-ou-rien : pas de **visibilité par couche** (voir la page nettoyée sans texte, par
  exemple) — exigerait `setVisible` par item et de reboucher le trou que ce mécanisme ouvrirait
  dans « enregistrer l'image courante ». Jalon ultérieur seulement si demandé.
- Raccourci clavier configurable non ajouté (coût amont jugé disproportionné pour un 3e
  déclencheur sans besoin exprimé).
- Portée strictement page originale vs état courant ; pas de comparaison patch par patch.

### Point de test manuel de Philippe

Page `funhome_012`, traduite et rendue (nettoyage + texte présents).

1. Bouton **Original** (colonne Outils) : la page passe à l'original ; reclic → retour à l'état
   traduit.
2. Cliquer dans la page (pour lui donner le focus) puis maintenir **Alt** : la page passe à
   l'original, le bouton s'enfonce visuellement ; relâcher Alt → retour à l'état traduit.
3. Placer le curseur dans le champ traduction, maintenir Alt : rien ne se passe. Taper « œ »
   (Option+O) : aucun clignotement de la page.
4. Voile actif (bouton ou Alt), lancer **Nettoyer** : l'écran reste à l'original pendant le
   traitement ; décocher le voile → le nettoyage est bien présent.
5. Voile actif, `Cmd+E` (enregistrer l'image courante) : le fichier produit contient le texte
   traduit et le nettoyage, pas l'original. Même vérification en export CBZ et export PSD.
6. `Cmd+Tab` vers une autre app puis retour : le voile se lève, le bouton se relève.
7. Changer de page : la nouvelle page s'affiche à l'original si le voile était actif au moment du
   changement (comportement attendu, à confirmer visuellement).
8. Passer en mode **webtoon** : le bouton est grisé, Alt n'a plus d'effet.

**Contre-épreuves** :
- Voile actif via le bouton, puis passage en webtoon : le voile disparaît immédiatement (garde
  dans `drawForeground`, indépendante du bouton).
- Fenêtre modale ouverte (dialogue de réglages, par exemple) pendant qu'Alt est maintenu : le
  voile ne s'arme pas.
- Alt maintenu, puis clic sur un élément de la scène sous le voile : l'élément réagit normalement
  (sélection, édition) malgré son invisibilité apparente.
