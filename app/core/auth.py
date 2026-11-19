"""Operator-configured local identities; no external authentication provider."""
import hashlib
import hmac
import uuid
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, field_validator


class IdentityConfig(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    role: Literal['owner', 'analyst']
    token_sha256: SecretStr
    connections: list[uuid.UUID] = Field(default_factory=list, max_length=1000)

    @field_validator('token_sha256')
    @classmethod
    def validate_digest(cls, value: SecretStr):
        digest = value.get_secret_value()
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('token_sha256 must be a lowercase SHA-256 hex digest')
        return value


class Actor(BaseModel):
    id: str
    role: Literal['owner', 'analyst']
    connections: list[uuid.UUID] = Field(default_factory=list)


def actor(request: Request) -> Actor:
    settings = request.app.state.settings
    authorization = request.headers.get('Authorization')
    if authorization is None:
        if settings.development_owner:
            return Actor(id='development-owner', role='owner')
        raise HTTPException(403, detail={'code': 'access_denied', 'message': 'Authentication is required'})
    scheme, separator, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not separator or len(token) < 32 or len(token) > 512:
        raise HTTPException(401, detail={'code': 'invalid_credentials', 'message': 'Invalid credentials'})
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    found = None
    for identity in settings.identities:
        if hmac.compare_digest(digest, identity.token_sha256.get_secret_value()):
            found = identity
    if found is None:
        raise HTTPException(401, detail={'code': 'invalid_credentials', 'message': 'Invalid credentials'})
    return Actor(id=found.id, role=found.role, connections=found.connections)


def require_owner(request: Request, principal: Annotated[Actor, Depends(actor)]):
    if principal.role != 'owner':
        raise HTTPException(403, detail={'code': 'access_denied', 'message': 'Owner access is required'})
    return request.app.state.settings


def require_connection(principal: Actor, connection_id: uuid.UUID):
    if principal.role != 'owner' and connection_id not in principal.connections:
        # Do not disclose whether a connection exists.
        raise HTTPException(404, detail={'code': 'connection_not_found', 'message': 'Connection not found'})
