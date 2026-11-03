"""Explicit historical fixtures; active application defaults are global."""
from optimizer.network import Network as CurrentNetwork
from optimizer.service import OptimizerSession as CurrentSession


def Network(*args, **kwargs):
    kwargs.setdefault('deployment','regional')
    kwargs.setdefault('constellation','legacy')
    return CurrentNetwork(*args, **kwargs)


def OptimizerSession(**kwargs):
    kwargs.setdefault('deployment','regional')
    kwargs.setdefault('constellation','legacy')
    return CurrentSession(**kwargs)
