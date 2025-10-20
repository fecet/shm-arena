"""Utility functions for serialization and data generation."""

import pickle
from typing import Any


def serialize(data: dict[str, Any]) -> bytes:
    """Serialize dictionary to bytes using pickle.

    Args:
        data: Dictionary to serialize

    Returns:
        Serialized bytes
    """
    return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize(data: bytes) -> dict[str, Any]:
    """Deserialize bytes to dictionary using pickle.

    Args:
        data: Serialized bytes

    Returns:
        Deserialized dictionary
    """
    return pickle.loads(data)


def generate_test_dict(size: int) -> dict[str, Any]:
    """Generate a test dictionary of specified size.

    Args:
        size: Number of key-value pairs

    Returns:
        Test dictionary with numeric keys and mixed-type values
    """
    return {
        f"key_{i}": {
            "value": i,
            "squared": i * i,
            "text": f"test_value_{i}",
            "float": float(i) / 3.0,
        }
        for i in range(size)
    }
