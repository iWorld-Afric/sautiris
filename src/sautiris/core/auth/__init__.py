"""Authentication providers for SautiRIS."""

from sautiris.core.auth.apikey import APIKeyAuthProvider
from sautiris.core.auth.base import AuthProvider, AuthUser
from sautiris.core.auth.keycloak import KeycloakAuthProvider
from sautiris.core.auth.oauth2 import OAuth2AuthProvider

__all__ = [
    "APIKeyAuthProvider",
    "AuthProvider",
    "AuthUser",
    "KeycloakAuthProvider",
    "OAuth2AuthProvider",
]
