from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd
from scipy.spatial import KDTree

_DF: pd.DataFrame | None = None
_COORDS = None
_TREE: KDTree | None = None


def _data_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "processed" / "with_embeddings.csv"


def get_data() -> Tuple[pd.DataFrame, object, KDTree]:
    global _DF, _COORDS, _TREE

    if _DF is None:
        _DF = pd.read_csv(_data_path())

    if _COORDS is None:
        _COORDS = _DF[["x", "y", "z"]].values

    if _TREE is None:
        _TREE = KDTree(_COORDS)

    return _DF, _COORDS, _TREE
