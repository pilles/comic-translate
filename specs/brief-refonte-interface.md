# Brief — refonte de l'interface et du parcours

> **Document de cadrage, pas une spec exécutable.** Rédigé le 2026-09-21 pour servir de point
> de départ à une discussion de conception (Claude Desktop, mode chat + design), après trois
> lots de travail sur le fork (specs 01, 02, 03 jalons A et B).
>
> Objectif de ce document : arrêter de tâtonner fonction par fonction, poser une vision
> d'ensemble du parcours, et n'ouvrir le chantier qu'une fois la cible décidée.

---

## 1. Ce qu'est le produit

Lire des BD anglaises achetées (CBZ) en français, avec une traduction **100 % locale**
(Ollama sur un Mac Mini), et corriger à la main ce que la machine rate.

**But exprimé par Philippe (2026-09-13)** :
- « un outil qui fait tout tout seul », mais il sait que c'est illusoire sans contrôle visuel ;
- ce qui a manqué à la première utilisation : « quelque chose qui permette de **se tromper et de
  revenir en arrière** pour corriger » ;
- « j'aime le côté simple de l'interface, **mais pas le côté pauvre** » ;
- qualité visée : « **correct sans être irréprochable** » ;
- il veut **tester lui-même à chaque grande modification**.

Usage strictement personnel. Mac. Aucune page de BD dans git.

---

## 2. Le parcours aujourd'hui

Barre d'actions, de gauche à droite :

`Détecter` → `Reconnaître` → `Traduire` → `Segmenter` → `Nettoyer` → `Rendre`

Six boutons de même poids visuel, qui exposent **le pipeline interne**, pas la tâche. Rien
n'indique l'ordre, ni où on en est, ni ce qui a déjà été fait sur la page. Il existe aussi un
mode « Automatique » et un bouton « Traduire tout » (lot) qui font la même chose sans contrôle.

Panneau de droite, de haut en bas, quatre sujets sans rapport empilés :
1. langues source et cible,
2. champ texte source + champ traduction (hauteur fixe 120 px, texte long tronqué),
3. police, taille, interligne, couleur, alignement, gras/italique/souligné, contour,
4. outils de dessin de boîte, puis outils de nettoyage (pinceau, gomme, épaisseur).

Colonne de gauche : vignettes des pages. Aucun état par page.

---

## 3. Défauts mesurés (pas supposés)

Relevés dans le code et vérifiés (références complètes dans `specs/03-inventaire.md` §5) :

| # | Défaut | Preuve |
|---|---|---|
| 1 | « Reconnaître » **ne dit rien** et ne fait rien s'il n'y a aucun rectangle sur la page | `pipeline/ocr_handler.py:24`, condition sans `else` |
| 2 | Le résultat de la reconnaissance **n'est visible nulle part** tant qu'on ne clique pas sur une bulle | champ source rempli seulement à la sélection, `app/controllers/rect_item.py:51-60` |
| 3 | Les deux champs texte sont **vidés à chaque changement de page** et **après « Rendre »** | `image.py:1129`, `text.py:929` |
| 4 | « Rendre » **efface les rectangles** ; pour re-sélectionner une bulle il faut `Ctrl+Shift+R`, que rien ne signale | `text.py:947`, raccourci seul |
| 5 | La **sauvegarde automatique est désactivée par défaut** ; son interrupteur est dans la barre de titre, ses réglages dans Réglages > Projet, sans lien visuel | `projects.py:61-66`, `title_bar.py:692-700`, `project_page.py:26-30` |
| 6 | Aucune invite à **enregistrer le projet** à l'ouverture d'un CBZ | `projects.py:214-228` |
| 7 | L'instantané de récupération n'est proposé **que si aucune page n'est chargée** | `projects.py:433-436` |
| 8 | Aucun **état par page** (détectée ? traduite ? nettoyée ? rendue ?) nulle part | aucune donnée d'état dans la liste de pages |
| 9 | Les champs texte font **120 px en dur** : une légende longue est tronquée et défile | `workspace.py:156`, `:166` |
| 10 | Langue source « Auto » **colle les lignes sans espace** (« MYBROTHERS ») ; « English » donne un texte propre | mesuré le 2026-09-13 sur 2 pages |

À quoi s'ajoutent deux pannes silencieuses corrigées pendant les lots précédents, qui illustrent
le même problème de retour utilisateur : l'OCR rendait du vide sans erreur (locale système,
ADR-009), et le détecteur classait les légendes larges en bulles, ce qui coupait leur masque
(ADR-011). Dans les deux cas, **rien à l'écran ne signalait l'anomalie**.

---

## 4. Ce qui est déjà construit et qu'il faut garder

- **Traduction locale** par Ollama, traducteur Custom, sans compte ni télémétrie (specs 01).
- **Nettoyage** amélioré : remplissage uni des légendes, protection des bords de case (spec 02).
- **Historique par bulle** : chaque reconnaissance, traduction et correction manuelle est
  conservée et restaurable en un clic, persistée dans le projet (spec 03 jalon A, ADR-012).
  Actuellement derrière une petite icône ambiguë sous le champ traduction.
- **Voir l'original** : bouton et touche Alt qui affichent la page d'origine par-dessus le texte
  et le nettoyage, sans rien modifier (spec 03 jalon B, ADR-013).
- **Projets `.ctpr`** : base SQLite qui conserve blocs, textes, traductions, patchs, tracés,
  langues ; sauvegarde auto et instantanés de récupération existent.
- **Exports** image, CBZ, PDF, PSD en trois calques (texte éditable, patchs, image brute).

---

## 5. Contraintes non négociables pour toute refonte

1. **C'est un fork.** Base `filvyb/comic-translate`. Toute ligne modifiée dans un fichier amont
   porte `# fork:` et doit rester minimale, pour pouvoir rebaser. Le code nouveau va dans des
   modules nouveaux (`modules/history/`, `modules/view/`, `modules/cleaning/` aujourd'hui).
2. **PySide6 / Qt Widgets.** Pas de réécriture en QML ni en web.
3. **Ne rien casser** : compatibilité des projets `.ctpr` dans les deux sens, export PSD
   inchangé, aucun appel réseau hors HuggingFace et l'endpoint Ollama.
4. **Aucun compte, aucune télémétrie.**
5. Temps disponible limité : la refonte doit être **découpée en jalons testables** un par un.

---

## 6. Diagnostic en une phrase

L'application expose **son pipeline** là où l'utilisateur attend **une tâche** : elle demande de
connaître l'ordre des six étapes, ne dit jamais où on en est, ne signale pas ses échecs, et range
côte à côte des réglages qui n'ont rien à voir. Tout le reste (qualité de traduction, de
nettoyage, de rendu) est déjà correct.

---

## 7. Pistes à discuter (rien n'est tranché)

- **Une action principale par page** (« Traduire cette page ») avec les six étapes visibles
  comme un **état d'avancement**, pas comme six boutons aveugles ; chaque étape reste
  déclenchable seule pour reprendre la main.
- **État par page dans la liste de gauche** : pastilles détectée / reconnue / traduite /
  nettoyée / rendue, pour savoir où on en est dans un album de 240 pages.
- **Panneau de droite contextuel** : quand une bulle est sélectionnée → source, traduction,
  historique, police ; quand rien n'est sélectionné → réglages de la page. Aujourd'hui tout est
  empilé en permanence.
- **Retours explicites** : « aucun bloc détecté sur cette page », « 10 bulles reconnues »,
  « modèle indisponible », au lieu du silence.
- **Corriger sans peur** : historique de bulle visible plutôt que caché derrière une icône,
  annulation qui survit à la fermeture, comparaison avec l'original toujours à portée.
- **Le premier lancement** : proposer d'enregistrer le projet, activer la sauvegarde auto par
  défaut, choisir la langue source une fois.
- **Outils de dessin et de nettoyage** regroupés dans une vraie barre d'outils, hors du panneau
  de texte.

---

## 8. Questions ouvertes pour la discussion

1. Le parcours cible est-il **page par page** (on corrige au fil de l'eau) ou **album d'abord,
   corrections ensuite** (traitement en lot puis revue) ? Les deux existent aujourd'hui sans que
   l'interface dise lequel est le chemin normal.
2. Que veut-on voir **par défaut** en ouvrant une page déjà traitée : le rendu final, ou le
   rendu avec les bulles cliquables ?
3. Jusqu'où va la refonte : réagencement du panneau existant, ou nouvelle fenêtre principale ?
   (le second coûte beaucoup plus cher en rebase)
4. Faut-il un **mode revue** dédié (page suivante / bulle suivante au clavier) pour corriger un
   album complet rapidement ?
5. Quelle place pour le **lot** (« Traduire tout ») dans le parcours cible ?

---

## 9. Pour reprendre la discussion ailleurs

Tout l'historique du projet est dans le dépôt, pas dans une conversation :

- `CLAUDE.md` — carte des modules, règles du fork, défauts amont connus.
- `JOURNAL.md` — chronologie des sessions, mesures, incidents.
- `specs/decisions.md` — ADR-001 à 013, le *pourquoi* de chaque décision.
- `specs/00-feuille-de-route.md` — cadrage général et contraintes.
- `specs/03-inventaire.md` — inventaire mesuré de l'existant (projets, annulation, calques,
  découvrabilité). **C'est le document le plus utile pour une discussion d'interface.**
- `specs/01`, `specs/02`, `specs/03` — les lots déjà livrés.
