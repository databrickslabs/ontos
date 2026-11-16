"""Starting the managers again lets the previous ones go.

The integration ``client`` fixture runs ``initialize_managers`` for every test. When
startup kept a manager in a module-level list, every test's whole manager graph
(search index, ontology graphs, ...) stayed in memory until the worker ended, and
the CI runner ran out of memory.
"""
import gc
import weakref

from src.app import app
from src.common.search_registry import SEARCHABLE_ASSET_MANAGERS
from src.utils import startup_tasks


def test_the_search_registry_holds_classes_only(client):
    assert all(isinstance(entry, type) for entry in SEARCHABLE_ASSET_MANAGERS)


def test_starting_the_managers_again_frees_the_previous_ones(client):
    previous = weakref.ref(app.state.tags_manager)

    startup_tasks.initialize_managers(app)  # the client fixture puts app.state back afterwards
    app.state.search_manager = None  # the fixture's index still lists the previous managers
    gc.collect()

    assert previous() is None
