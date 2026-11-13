"""Entry point for Role E's harness:  --adapter e_adapter:predict

Thin re-export so E can pass a short module name after putting the project
folder (or ``lu-recycle-b/src``) on PYTHONPATH.
"""

from reco.adapter import predict  # noqa: F401

__all__ = ["predict"]
