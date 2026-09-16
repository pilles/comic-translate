"""Régression : reset de LC_NUMERIC après création de QApplication (fork comic.py).

Contexte (voir commentaire dans `comic.py`, ligne "fork:"): sur une machine
dont la locale système est `fr_FR` (virgule décimale), Qt applique cette
locale C au process dès `QApplication(sys.argv)`. Si `onnxruntime` est
importé *après* ce point sans reset de `LC_NUMERIC`, le runtime interprète
mal des flottants internes et le modèle PP-OCR
`en_PP-OCRv5_rec_mobile_infer.onnx` produit une sortie constante (OCR vide,
aucune exception levée). `locale.setlocale(locale.LC_NUMERIC, "C")` juste
après la création de `QApplication` corrige le problème.

Preuves et scripts de diagnostic (hors dépôt, scratchpad de session) :
modes `L1_setlocale_fr_then_import` (cassé) vs `Q2_qt_resetC_then_import`
(OK), rejoués ici en sous-processus contre une vraie entrée
(`tests/fixtures/ppocr_en_line.npy`, tenseur 1x3x48x134 float32 normalisé
issu d'une ligne de texte réelle — pas une page de BD).
"""

from __future__ import annotations

import ast
import locale
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMIC_PY = REPO_ROOT / "comic.py"
BENCH_CLEANING_PY = REPO_ROOT / "tools" / "bench_cleaning.py"
FIXTURE_NPY = REPO_ROOT / "tests" / "fixtures" / "ppocr_en_line.npy"
MODEL_RELATIVE_PATH = os.path.join(
    "models", "ocr", "ppocr-v5-onnx", "en_PP-OCRv5_rec_mobile_infer.onnx"
)


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _line_offsets_matching(func: ast.FunctionDef, predicate) -> list[int]:
    """Renvoie les numéros de ligne (1-based, relatifs au fichier) des noeuds
    de `func` dont la représentation textuelle du call/attribut satisfait
    `predicate`. On marche l'AST plutôt que de faire du texte brut pour
    éviter les faux positifs (commentaires, chaînes)."""
    lines: list[int] = []
    for node in ast.walk(func):
        if predicate(node):
            lines.append(node.lineno)
    return lines


def _is_qapplication_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # QApplication(...) ou qtwidgets.QApplication(...) etc.
    name = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    return name == "QApplication"


def _is_setlocale_c_numeric_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    if name != "setlocale":
        return False
    if not node.args:
        return False
    first_arg = node.args[0]
    # locale.LC_NUMERIC
    is_lc_numeric = isinstance(first_arg, ast.Attribute) and first_arg.attr == "LC_NUMERIC"
    return is_lc_numeric


def test_comic_entrypoint_resets_lc_numeric():
    """`main()` de comic.py doit remettre LC_NUMERIC sur "C" APRES la création
    de QApplication(sys.argv), sinon onnxruntime peut miscalculer en silence
    sous une locale système à virgule décimale (ex. fr_FR)."""
    source = COMIC_PY.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(COMIC_PY))

    main_func = _find_function(tree, "main")
    assert main_func is not None, (
        "comic.py doit définir une fonction main() — introuvable par analyse AST."
    )

    qapp_lines = _line_offsets_matching(main_func, _is_qapplication_call)
    assert qapp_lines, (
        "Aucun appel QApplication(...) trouvé dans main() : le point d'ancrage "
        "du correctif a disparu (comic.py a peut-être été refactoré)."
    )

    setlocale_lines = _line_offsets_matching(main_func, _is_setlocale_c_numeric_call)
    assert setlocale_lines, (
        'Aucun appel locale.setlocale(locale.LC_NUMERIC, "C") trouvé dans '
        "main() : le correctif anti-onnxruntime/locale fr_FR semble avoir été "
        "retiré de comic.py."
    )

    first_qapp_line = min(qapp_lines)
    first_reset_line = min(setlocale_lines)
    assert first_reset_line > first_qapp_line, (
        f"locale.setlocale(LC_NUMERIC, 'C') doit être appelé APRES "
        f"QApplication(sys.argv) dans main() (QApplication ligne "
        f"{first_qapp_line}, reset ligne {first_reset_line}). Si le reset "
        f"précède la création de QApplication, Qt réapplique la locale "
        f"système ensuite et le bug (OCR vide sous fr_FR) réapparaît."
    )


def _model_path() -> Path:
    from modules.utils.paths import get_user_data_dir

    return Path(get_user_data_dir()) / MODEL_RELATIVE_PATH


def _fr_fr_locale_available() -> bool:
    try:
        current = locale.setlocale(locale.LC_ALL)
        try:
            locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
            return True
        finally:
            locale.setlocale(locale.LC_ALL, current)
    except locale.Error:
        return False


def _run_ort_probe(env_extra: dict[str, str]) -> int:
    """Exécute en sous-processus : reset/force la locale demandée, importe
    onnxruntime, charge le modèle PP-OCR-rec, exécute sur le tenseur fixture
    et imprime (dernière ligne stdout) le nombre de pas dont l'argmax != 0.

    Isolé en sous-processus pour ne jamais modifier la locale du process
    pytest lui-même (setlocale() est un état process-global)."""
    code = f"""
import locale, sys
mode = {env_extra["MODE"]!r}
if mode == "reset_c":
    locale.setlocale(locale.LC_NUMERIC, "C")
elif mode == "force_fr":
    locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")
import numpy as np
import onnxruntime as ort
x = np.load({str(FIXTURE_NPY)!r})
sess = ort.InferenceSession({str(env_extra["MODEL_PATH"])!r}, providers=["CPUExecutionProvider"])
out = sess.run(None, {{sess.get_inputs()[0].name: x}})[0]
nonzero_steps = int((out.argmax(-1) != 0).sum())
print(nonzero_steps)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"Le sous-processus de sonde onnxruntime (mode={env_extra['MODE']}) a "
        f"échoué (code {proc.returncode}).\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return int(last_line)


def test_onnxruntime_rec_model_under_fr_locale():
    """Documente et verrouille le comportement onnxruntime/locale :

    (a) LC_NUMERIC="C" avant import onnxruntime -> le modèle PP-OCR-rec
        produit une sortie non constante sur une vraie ligne de texte
        (argmax != 0 sur au moins un pas). C'est l'assertion bloquante :
        c'est exactement ce que garantit le correctif de comic.py.
    (b) LC_ALL="fr_FR.UTF-8" avant import onnxruntime -> si le bug
        d'environnement est présent sur cette machine, argmax != 0 vaut 0
        partout (OCR silencieusement vide). Ce n'est PAS une assertion
        bloquante ici (c'est un bug d'environnement onnxruntime/locale, pas
        un bug de comic.py) : on se contente de l'observer et de le
        documenter via un avertissement, pour information/traçabilité.
        Si fr_FR.UTF-8 n'est pas installée sur la machine, (b) est ignorée.
    """
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        pytest.skip("onnxruntime n'est pas installé.")

    model_path = _model_path()
    if not model_path.exists():
        pytest.skip(f"Modèle PP-OCR non présent en cache local : {model_path}")

    if not FIXTURE_NPY.exists():
        pytest.skip(f"Fixture d'entrée absente : {FIXTURE_NPY}")

    # (a) cas corrigé : doit produire une sortie non constante.
    nonzero_steps_c = _run_ort_probe({"MODE": "reset_c", "MODEL_PATH": str(model_path)})
    assert nonzero_steps_c > 0, (
        "Avec LC_NUMERIC='C' (comportement attendu après le correctif de "
        "comic.py), le modèle PP-OCR-rec doit produire une sortie non "
        f"constante sur une vraie ligne de texte (obtenu : {nonzero_steps_c} "
        "pas avec argmax != 0). Régression sur onnxruntime/le modèle en cache "
        "possible."
    )

    # (b) documentaire seulement : observe si le bug d'environnement est
    # présent sous fr_FR, sans faire échouer le test.
    if not _fr_fr_locale_available():
        warnings.warn(
            "Locale fr_FR.UTF-8 non disponible sur cette machine : partie (b) "
            "du test (reproduction du bug sous locale système fr_FR) ignorée.",
            stacklevel=1,
        )
        return

    nonzero_steps_fr = _run_ort_probe({"MODE": "force_fr", "MODEL_PATH": str(model_path)})
    if nonzero_steps_fr == 0:
        warnings.warn(
            "Bug d'environnement onnxruntime/locale confirmé sur cette "
            "machine : sous LC_ALL='fr_FR.UTF-8' (sans reset LC_NUMERIC), le "
            "modèle PP-OCR-rec produit une sortie constante (0 pas avec "
            "argmax != 0), soit un OCR silencieusement vide. C'est "
            "exactement le bug que corrige comic.py. Voir "
            "comic.py::main() pour le correctif (locale.setlocale("
            "locale.LC_NUMERIC, 'C') après QApplication(sys.argv)).",
            stacklevel=1,
        )
    else:
        warnings.warn(
            f"Sous LC_ALL='fr_FR.UTF-8', le modèle PP-OCR-rec produit encore "
            f"une sortie non constante ({nonzero_steps_fr} pas avec argmax "
            "!= 0) sur cette machine : le bug d'environnement onnxruntime/"
            "locale décrit dans comic.py n'est pas reproduit ici (dépend de "
            "la version d'onnxruntime / de la plateforme). Le correctif "
            "reste défensif et sans coût.",
            stacklevel=1,
        )


def test_tools_bench_cleaning_qt_mode_resets_locale():
    """`tools/bench_cleaning.py` (`_ensure_qt_app`) crée sa propre QApplication
    pour le mode `--manual-mask qt`. Ce banc n'utilise pas l'OCR, mais il crée
    QApplication de la même façon que comic.py et est donc exposé au même
    piège de locale pour tout code numérique importé après coup dans le même
    process (numpy/onnxruntime/etc. via des imports différés). Même correctif
    que comic.py (ADR-009) : on verrouille qu'il est bien appliqué ici aussi."""
    source = BENCH_CLEANING_PY.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(BENCH_CLEANING_PY))

    ensure_qt_app = _find_function(tree, "_ensure_qt_app")
    assert ensure_qt_app is not None, (
        "_ensure_qt_app() introuvable dans tools/bench_cleaning.py : le point "
        "d'ancrage de cette vérification a changé de nom/emplacement."
    )

    qapp_lines = _line_offsets_matching(ensure_qt_app, _is_qapplication_call)
    assert qapp_lines, (
        "_ensure_qt_app() ne semble plus créer de QApplication(...) : vérification à adapter."
    )

    setlocale_lines = _line_offsets_matching(ensure_qt_app, _is_setlocale_c_numeric_call)
    assert setlocale_lines, (
        "tools/bench_cleaning.py::_ensure_qt_app() crée une QApplication "
        "(mode --manual-mask qt) sans remettre locale.LC_NUMERIC à 'C' "
        "ensuite, contrairement à comic.py::main() (ADR-009). C'est le même "
        "piège Qt/locale : tout code numérique (numpy/onnxruntime) importé "
        "après coup dans ce process, sous une locale système à virgule "
        "décimale (fr_FR), serait exposé au même risque silencieux."
    )

    first_qapp_line = min(qapp_lines)
    first_reset_line = min(setlocale_lines)
    assert first_reset_line > first_qapp_line, (
        "locale.setlocale(LC_NUMERIC, 'C') doit suivre la création de "
        "QApplication dans _ensure_qt_app(), pas la précéder."
    )
