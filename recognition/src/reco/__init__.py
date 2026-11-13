"""Module B -- image recognition and model access for the LU Recycle Assistant.

Public surface used by the rest of the project::

    from reco import Recognizer, load_config

    rec = Recognizer()                       # reads env config + item catalogue
    result = rec.recognize("photo.jpg")      # RecognitionResult (validated)
    result.item_id                           # -> "plastic_beverage_bottle"
    result.catalogue_status                  # -> matched | ambiguous | out_of_scope | unresolved
    result.display_name_en                   # canonical catalogue name for the card
    result.unknown_conditions                # -> ["has_residue", "is_clean"]
    rec.baseline("photo.jpg")                # BaselineResult, for comparison

Nothing here decides how to dispose of an item; that is module C.
"""

from .catalog import Catalogue, CatalogueError, CatalogueItem, load_catalogue
from .config import Config, load_config
from .pipeline import Outcome, RecognitionFailure, Recognizer
from .schema import (
    SCHEMA_VERSION,
    BaselineResult,
    Identification,
    ImageQuality,
    Material,
    RecognitionResult,
    Trace,
    VisibleState,
)

__all__ = [
    "SCHEMA_VERSION",
    "BaselineResult",
    "Catalogue",
    "CatalogueError",
    "CatalogueItem",
    "Config",
    "Identification",
    "ImageQuality",
    "Material",
    "Outcome",
    "RecognitionFailure",
    "RecognitionResult",
    "Recognizer",
    "Trace",
    "VisibleState",
    "load_catalogue",
    "load_config",
]

__version__ = "0.2.0"
