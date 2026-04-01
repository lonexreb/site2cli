"""Known OAuth provider configurations for device flow."""

from __future__ import annotations

from site2cli.config import get_config
from site2cli.models import OAuthProviderConfig

KNOWN_PROVIDERS: dict[str, dict] = {
    "github": {
        "name": "github",
        "device_authorization_endpoint": "https://github.com/login/device/code",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user"],
    },
    "google": {
        "name": "google",
        "device_authorization_endpoint": "https://oauth2.googleapis.com/device/code",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "scopes": ["openid", "profile", "email"],
    },
    "microsoft": {
        "name": "microsoft",
        "device_authorization_endpoint": (
            "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
        ),
        "token_endpoint": (
            "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        ),
        "scopes": ["openid", "profile", "email"],
    },
}


def get_provider_config(
    provider_name: str,
    client_id: str,
    scopes: list[str] | None = None,
) -> OAuthProviderConfig:
    """Get a pre-configured provider with the user's client_id."""
    if provider_name not in KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown provider: {provider_name}. "
            f"Available: {', '.join(KNOWN_PROVIDERS)}"
        )
    template = KNOWN_PROVIDERS[provider_name].copy()
    template["client_id"] = client_id
    if scopes is not None:
        template["scopes"] = scopes
    return OAuthProviderConfig(**template)


def load_custom_provider(domain: str) -> OAuthProviderConfig | None:
    """Load a custom OAuth provider config from disk."""
    config = get_config()
    path = config.data_dir / "auth" / f"{domain}.oauth.json"
    if not path.exists():
        return None
    with open(path) as f:
        return OAuthProviderConfig.model_validate_json(f.read())


def save_custom_provider(domain: str, provider: OAuthProviderConfig) -> None:
    """Save a custom OAuth provider config to disk."""
    config = get_config()
    auth_dir = config.data_dir / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    path = auth_dir / f"{domain}.oauth.json"
    with open(path, "w") as f:
        f.write(provider.model_dump_json(indent=2))
