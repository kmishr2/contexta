"""Generate a high-entropy token and its configuration digest; writes no files."""
import hashlib
import secrets


def main():
    token = secrets.token_urlsafe(32)
    print('Token (give only to the intended user):', token)
    print('SHA-256 (put in CONTEXA_IDENTITIES):', hashlib.sha256(token.encode()).hexdigest())


if __name__ == '__main__':
    main()
