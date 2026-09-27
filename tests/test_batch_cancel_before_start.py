"""Spec 04, jalon 2, sous-étape 2b-bis : correctif du défaut amont n°3 (ADR-014, amendement
ADR-018) dans `app/controllers/task_runner.py::TaskRunnerController.cancel_current_task`.

Défaut : un lot mis en file derrière une autre opération (typiquement un autosave) et annulé
avant d'avoir démarré ne déclenche jamais `on_batch_process_finished` en vidant la file ->
`_batch_active` reste bloqué à `True` pour toute la session (Translate All/Cancel grisés,
autosave coupée en silence). Le correctif planifie lui-même `on_batch_process_finished` via
`QtCore.QTimer.singleShot`, sauf si un lot est déjà *en cours d'exécution* (il se termine tout
seul) ou si la fenêtre est en fermeture (`shutdown()`).

Isolation en sous-processus (comme `tests/test_locale_onnxruntime.py::_run_ort_probe` et
`tests/test_pagestate.py`) : chaque scénario construit sa propre `QtCore.QCoreApplication` dans
un processus dédié. Nécessaire ici parce que `QCoreApplication`/`QApplication` est un singleton
processus : en créer une ici, dans le processus pytest partagé, romprait la suite `--gui`
(`pytest-qt` teste `QApplication.instance()` puis construit une vraie `QApplication` widgets si
`None` ; une `QCoreApplication` nue déjà en place serait réutilisée à tort et casserait les
tests Qt widgets qui s'exécutent dans le même processus). Aucun accès aux vraies QSettings ni au
vrai dossier de données : `FakeMain` n'expose que les attributs lus par
`cancel_current_task`/`on_batch_process_finished`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Script exécuté en sous-processus : construit une QCoreApplication, un `FakeMain` (QObject
# minimal, aucune vraie fenêtre/QSettings) et un `TaskRunnerController`, pose l'état de départ
# (file d'attente + opération "en cours" simulées), appelle `cancel_current_task()`, laisse
# tourner la boucle d'évènements un court instant, puis imprime un JSON (dernière ligne stdout).
_SCENARIO_TEMPLATE = """
import json
import sys
from unittest.mock import Mock

sys.path.insert(0, {repo_root!r})

from PySide6 import QtCore

from app.controllers.task_runner import TaskRunnerController


def _other_callback():
    pass


class FakeMain(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.current_worker = Mock()
        self._batch_active = {batch_active!r}
        self._batch_cancel_requested = False
        self.cancel_button = Mock()
        self.progress_bar = Mock()
        self.on_batch_process_finished_mock = Mock()
        if {is_shutting_down!r} is not None:
            self._is_shutting_down = {is_shutting_down!r}

    def on_batch_process_finished(self):
        self.on_batch_process_finished_mock()


def _fake_operation(kind, main):
    callback = main.on_batch_process_finished if kind == "batch" else _other_callback
    return {{
        "callback": None,
        "result_callback": None,
        "error_callback": None,
        "finished_callback": callback,
        "args": (),
        "kwargs": {{}},
    }}


app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
main = FakeMain()
controller = TaskRunnerController(main)

for kind in {queue_kinds!r}:
    controller.operation_queue.append(_fake_operation(kind, main))

current_kind = {current_kind!r}
controller._current_operation = (
    _fake_operation(current_kind, main) if current_kind is not None else None
)
controller.is_processing_queue = bool({queue_kinds!r}) or current_kind is not None

# Preuve « == et non is » : deux accès à une méthode liée créent deux objets distincts
# (bound methods), égaux par valeur mais pas identiques. On le calcule ici, sur la file telle
# qu'elle existe *avant* `cancel_current_task()`, avec l'expression exacte du correctif.
pending_via_eq = any(
    op["finished_callback"] == main.on_batch_process_finished for op in controller.operation_queue
)
pending_via_is = any(
    op["finished_callback"] is main.on_batch_process_finished for op in controller.operation_queue
)

controller.cancel_current_task()

for _ in range(100):
    app.processEvents()

result = {{
    "calls": main.on_batch_process_finished_mock.call_count,
    "queue_len": len(controller.operation_queue),
    "is_processing_queue": controller.is_processing_queue,
    "worker_cancel_called": main.current_worker.cancel.called,
    "pending_via_eq": pending_via_eq,
    "pending_via_is": pending_via_is,
}}
print(json.dumps(result))
"""


def _run_scenario(
    *,
    queue_kinds: list[str],
    current_kind: str | None,
    batch_active: bool,
    is_shutting_down: bool | None = None,
) -> dict:
    """Lance un scénario en sous-processus et renvoie le JSON imprimé.

    `queue_kinds` : opérations restées en file (chacune "batch" ou "other"), dans l'ordre.
    `current_kind` : opération en cours d'exécution simulée ("batch"/"other"), ou `None` si
    rien n'est en cours (file vide au repos).
    `is_shutting_down` : valeur de `main._is_shutting_down` ; `None` = attribut absent, pour
    exercer le repli `getattr(..., False)` du correctif.
    """
    code = _SCENARIO_TEMPLATE.format(
        repo_root=str(REPO_ROOT),
        queue_kinds=queue_kinds,
        current_kind=current_kind,
        batch_active=batch_active,
        is_shutting_down=is_shutting_down,
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"Sous-processus de scénario en échec (code {proc.returncode}).\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


def test_batch_queued_behind_non_batch_current_is_finished_once():
    """Lot en file derrière une opération non-lot en cours, Cancel -> terminé une fois."""
    result = _run_scenario(
        queue_kinds=["batch"],
        current_kind="other",
        batch_active=True,  # `_run_batch_for_paths` met `_batch_active = True` avant de mettre
        # en file, donc c'est déjà vrai au moment du Cancel, même si le lot n'a pas démarré.
    )
    assert result["calls"] == 1, result
    assert result["queue_len"] == 0, result
    assert result["is_processing_queue"] is False, result
    assert result["worker_cancel_called"] is True, result


def test_batch_running_plus_batch_queued_is_not_finished_by_the_fix():
    """Lot en cours + lot en file derrière, Cancel -> pas d'appel planifié par le correctif.

    Le lot en cours s'annule via `current_worker.cancel()` et appellera lui-même
    `on_batch_process_finished` à sa fin réelle (non simulée ici) ; le déclencher aussi pour le
    lot en file serait une double finalisation pendant que le premier tourne encore."""
    result = _run_scenario(
        queue_kinds=["batch"],
        current_kind="batch",
        batch_active=True,
    )
    assert result["calls"] == 0, result
    assert result["queue_len"] == 0, result
    assert result["is_processing_queue"] is False, result


def test_queue_without_batch_is_not_finished():
    """File sans aucun lot (ex. deux autosaves), Cancel -> pas d'appel planifié."""
    result = _run_scenario(
        queue_kinds=["other"],
        current_kind="other",
        batch_active=False,
    )
    assert result["calls"] == 0, result
    assert result["queue_len"] == 0, result


def test_finished_callback_comparison_must_use_eq_not_is():
    """Preuve que le correctif doit comparer par `==` : deux accès à la même méthode liée sont
    égaux mais jamais identiques. Si `cancel_current_task` comparait par `is` (mutation), la
    détection du lot en file échouerait silencieusement (`pending_via_is` est `False` ici alors
    que le vrai correctif, qui compare par `==`, termine bien le lot : `calls == 1`)."""
    result = _run_scenario(
        queue_kinds=["batch"],
        current_kind="other",
        batch_active=True,
    )
    assert result["pending_via_eq"] is True, result
    assert result["pending_via_is"] is False, result
    assert result["calls"] == 1, result


def test_shutdown_path_schedules_nothing():
    """`cancel_current_task` est aussi appelé par `shutdown()` (après `shutdown_autosave`) : en
    fermeture, ne rien planifier (risque documenté : un `singleShot` sur un `main` en cours de
    destruction ne s'exécuterait de toute façon pas forcément ; le correctif l'évite via
    `main._is_shutting_down`, déjà posé par `shutdown()` avant `cancel_current_task()`)."""
    result = _run_scenario(
        queue_kinds=["batch"],
        current_kind="other",
        batch_active=True,
        is_shutting_down=True,
    )
    assert result["calls"] == 0, result


def test_missing_is_shutting_down_attribute_falls_back_to_false():
    """`getattr(self.main, "_is_shutting_down", False)` : si l'attribut est absent (fausse
    fenêtre minimale), le correctif se comporte comme en fonctionnement normal."""
    result = _run_scenario(
        queue_kinds=["batch"],
        current_kind="other",
        batch_active=True,
        is_shutting_down=None,
    )
    assert result["calls"] == 1, result


def test_bound_method_identity_vs_equality_language_fact():
    """Fait de langage (indépendant de Qt) qui justifie `==` : deux accès à une méthode liée
    créent deux objets distincts (`is` False) mais égaux (`==` True)."""

    class _Foo:
        def method(self) -> None:
            pass

    foo = _Foo()
    first = foo.method
    second = foo.method
    assert first == second
    assert first is not second
