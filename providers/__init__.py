"""Пакет провайдеров LLM."""

from providers.base import Provider, error_result, ok_result

__all__ = ["Provider", "ok_result", "error_result"]
