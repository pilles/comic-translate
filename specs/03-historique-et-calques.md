# Spec 03 — Historique de page et calques dans l'app

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
- **E2 — Journal de page persisté** : liste horodatée des opérations (détection, OCR, traduction
  avec modèle et contexte utilisés, nettoyage avec méthode, éditions manuelles), sauvegardée dans
  le `.ctpr`, consultable dans un panneau.
  Inventaire : **quasi absent** — seul le rapport de lot est persisté (pages sautées et motif
  uniquement, ni modèle ni réglage ni opération réussie) (`03-inventaire.md` §1.6, verdict §5).
- **E3 — Versions de traduction par bloc** : chaque retraduction ou édition crée une version ;
  restaurer une version antérieure en un clic.
  Inventaire : **absent** — `TextBlock.translation` est un champ scalaire unique, écrasé en place
  par 7 chemins (`03-inventaire.md` §1.3, verdict §5, mesure §8.1).
- **E4 — Découvrabilité** : si l'inventaire montre que 1 et 2 sont couverts, les rendre visibles
  (proposition d'enregistrer le projet à l'ouverture d'un CBZ, champ source toujours affiché).
  Inventaire : **partiellement couvert** — le socle (texte source, historique, patchs) existe et
  survit à la réouverture, mais reste peu visible : champs vidés au changement de page et après
  rendu, aucune étiquette, sauvegarde auto désactivée par défaut (`03-inventaire.md` §5 détail E4).

Philippe arbitre la liste retenue **après** l'inventaire. Ordre de priorité proposé :
E4 → E1 → E3 → E2.

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
