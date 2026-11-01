"""Secrets in the system's keychain (API keys, passwords), never in settings.json: the macOS
Keychain (`security`), Windows' Credential Manager or Linux's Secret Service (keyring).

    keychain.get("AnyAssistant LLM", "openai")  → the key, or None
    keychain.put("AnyAssistant LLM", "openai", "sk-…")
    keychain.forget("AnyAssistant LLM", "openai")
"""

import subprocess
import sys


def get(service: str, account: str) -> str | None:
    if sys.platform != "darwin":
        try:
            import keyring

            return keyring.get_password(service, account)
        except Exception:  # no keyring backend (a server with no desktop)
            return None
    done = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                          capture_output=True, text=True)
    return done.stdout.rstrip("\n") if done.returncode == 0 else None


def put(service: str, account: str, secret: str):
    if sys.platform != "darwin":
        import keyring

        return keyring.set_password(service, account, secret)
    subprocess.run(["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret],
                   check=True, capture_output=True)


def forget(service: str, account: str):
    if sys.platform != "darwin":
        try:
            import keyring

            keyring.delete_password(service, account)
        except Exception:
            pass
        return
    subprocess.run(["security", "delete-generic-password", "-s", service, "-a", account], capture_output=True)
