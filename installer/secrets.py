"""
n8n's image (2.x) needs a real admin email/password - the first secret
this project has ever needed to generate. Mirrors Vulcan's generate_
authelia_secrets(): write once, never overwrite, so a later regenerate
never invalidates a real admin login already in use. Password
generation matches ODS's own real approach (installers/phases/06-
directories.sh: openssl rand -base64 16) - secrets.token_urlsafe() is
the direct Python equivalent.

Neither of the two env-var mechanisms this project tried actually
provisions n8n's owner account - both checked directly against n8n
2.6.4's own installed source in a running container, not assumed:
N8N_DEFAULT_ADMIN_EMAIL/PASSWORD (what ODS's compose sets, copied here
originally) and N8N_INSTANCE_OWNER_MANAGED_BY_ENV/EMAIL/PASSWORD_HASH
(what n8n's own docs describe) both got zero real matches when grepped
against the image's actual dist/ source. The real, only mechanism is a
one-time unauthenticated POST to /rest/owner/setup, taking a plaintext
password that n8n hashes itself server-side - confirmed for real by
calling it directly and then logging in with the same credentials. n8n's
own first-run setup wizard makes that call for you, so this project
still just generates the credentials and tells the user to enter them
into that wizard once - see generate.py's n8n warning message.
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
