"""
n8n's image (2.x) requires a real admin email/password at container
start (N8N_DEFAULT_ADMIN_EMAIL/N8N_DEFAULT_ADMIN_PASSWORD, both
":?must be set" in ODS's own compose - confirmed by reading it, not
assumed) - the first secret this project has ever needed to generate.
Mirrors Vulcan's generate_authelia_secrets(): write once, never
overwrite, so a later regenerate never invalidates a real admin login
already in use. Password generation matches ODS's own real approach
(installers/phases/06-directories.sh: openssl rand -base64 16) -
secrets.token_urlsafe() is the direct Python equivalent.
"""

import json
import secrets as _secrets
from pathlib import Path


N8N_CREDENTIALS_FILENAME = ".n8n-credentials.json"
N8N_DEFAULT_EMAIL = "admin@anvil.local"


def load_or_create_n8n_credentials(output_dir: Path) -> dict:

    path = output_dir / N8N_CREDENTIALS_FILENAME

    if path.exists():

        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            pass  # corrupt/unreadable - fall through and regenerate

    credentials = {"email": N8N_DEFAULT_EMAIL, "password": _secrets.token_urlsafe(16)}
    path.write_text(json.dumps(credentials, indent=2))
    return credentials
