"""
kite_login.py — Semi-automated Kite access token refresher.

Kite access tokens expire every day at midnight IST.
Full automation is NOT possible via the Kite API (login requires
a browser OTP step). This script handles the post-OTP step only.

FLOW (run each morning before market open):
  1. GitHub Actions runs this via cron at 08:00 IST (02:30 UTC)
  2. The script generates the Kite login URL and sends it to Telegram
  3. You open the URL on your phone, complete OTP
  4. Kite redirects to your registered redirect URL with ?request_token=xxx
  5. You send the request_token to your Telegram bot (or enter it via env)
  6. This script exchanges it for an access_token
  7. The new access_token is stored in a GitHub repo secret via GitHub API

NOTE:
  Steps 3-5 require a one-time daily manual action (OTP on phone).
  This is a Kite/SEBI security requirement — it cannot be bypassed.

ALTERNATIVE (recommended for true automation):
  Use a TOTP-based approach if your Kite account has TOTP enabled.
  Set KITE_TOTP_SECRET in GitHub Secrets and this script will handle
  the full login automatically.
"""

import os
import sys
import logging
import requests
import pyotp
from kiteconnect import KiteConnect
from telegram import _send as telegram_send

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kite_login")

KITE_API_KEY    = os.environ["KITE_API_KEY"]
KITE_API_SECRET = os.environ["KITE_API_SECRET"]

# Optional: if TOTP is enabled on your Kite account
KITE_TOTP_SECRET = os.environ.get("KITE_TOTP_SECRET", "")

# GitHub API — to update the secret after login
GITHUB_TOKEN    = os.environ.get("GH_PAT", "")
GITHUB_REPO     = os.environ.get("GITHUB_REPOSITORY", "")    # owner/repo

# If you are manually providing the request_token via env (step 5 above)
REQUEST_TOKEN   = os.environ.get("KITE_REQUEST_TOKEN", "")


def update_github_secret(secret_name: str, secret_value: str):
    """Update a GitHub repo secret via the GitHub REST API."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("GH_PAT or GITHUB_REPOSITORY not set — skipping secret update.")
        return

    # Get repo public key for secret encryption
    key_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
    }
    key_resp = requests.get(key_url, headers=headers)
    key_resp.raise_for_status()
    pub_key_data = key_resp.json()

    # Encrypt secret value with repo public key (libsodium)
    from base64 import b64encode
    from nacl import encoding, public as nacl_public

    public_key = nacl_public.PublicKey(
        pub_key_data["key"].encode(), encoding.Base64Encoder()
    )
    box       = nacl_public.SealedBox(public_key)
    encrypted = b64encode(box.encrypt(secret_value.encode())).decode()

    # PUT new secret
    put_url = (
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/actions/secrets/{secret_name}"
    )
    payload = {
        "encrypted_value": encrypted,
        "key_id":          pub_key_data["key_id"],
    }
    put_resp = requests.put(put_url, headers=headers, json=payload)
    put_resp.raise_for_status()
    logger.info(f"GitHub secret '{secret_name}' updated successfully.")


def get_totp() -> str:
    if not KITE_TOTP_SECRET:
        return ""
    totp = pyotp.TOTP(KITE_TOTP_SECRET)
    return totp.now()


def run():
    kite = KiteConnect(api_key=KITE_API_KEY)

    # ── TOTP auto-login path ──────────────────────────────────
    if KITE_TOTP_SECRET and not REQUEST_TOKEN:
        logger.info("TOTP secret found — attempting automated login …")
        try:
            import urllib.parse, re
            import mechanize    # pip install mechanize

            login_url = kite.login_url()
            br = mechanize.Browser()
            br.set_handle_robots(False)
            br.open(login_url)

            # Fill user_id and password
            kite_user_id  = os.environ["KITE_USER_ID"]
            kite_password = os.environ["KITE_PASSWORD"]
            br.select_form(nr=0)
            br["user_id"]  = kite_user_id
            br["password"] = kite_password
            br.submit()

            # Fill TOTP
            totp_code = get_totp()
            br.select_form(nr=0)
            br["totp"] = totp_code
            resp = br.submit()

            # Extract request_token from redirect URL
            final_url   = br.geturl()
            match       = re.search(r"request_token=([^&]+)", final_url)
            if not match:
                raise ValueError(f"request_token not found in URL: {final_url}")
            req_token = match.group(1)
            logger.info(f"request_token obtained via TOTP: {req_token[:8]}…")

        except Exception as e:
            logger.error(f"TOTP auto-login failed: {e}")
            # Fall back to sending manual URL
            login_url = kite.login_url()
            telegram_send(
                f"⚠️ <b>Kite TOTP login failed</b>\n"
                f"Please login manually:\n{login_url}\n"
                f"Then re-run with KITE_REQUEST_TOKEN set."
            )
            sys.exit(1)

    elif REQUEST_TOKEN:
        # ── Manual request_token provided ─────────────────────
        req_token = REQUEST_TOKEN
        logger.info(f"Using provided request_token: {req_token[:8]}…")

    else:
        # ── Send login URL to Telegram for manual OTP ─────────
        login_url = kite.login_url()
        telegram_send(
            f"🔑 <b>Kite Daily Login Required</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Open this URL, complete OTP, then send me the "
            f"<code>request_token</code> from the redirect URL:\n\n"
            f"<code>{login_url}</code>\n\n"
            f"<i>Token expires at midnight IST — please complete before 09:15 AM</i>"
        )
        logger.info("Login URL sent to Telegram. Waiting for manual token.")
        sys.exit(0)     # Exit cleanly; another run handles the token exchange

    # ── Exchange request_token for access_token ───────────────
    try:
        session_data = kite.generate_session(req_token, api_secret=KITE_API_SECRET)
        access_token = session_data["access_token"]
        logger.info(f"Access token obtained: {access_token[:8]}…")

        # Update GitHub secret so all subsequent workflow runs use new token
        update_github_secret("KITE_ACCESS_TOKEN", access_token)

        telegram_send(
            f"✅ <b>Kite Login Successful</b>\n"
            f"Access token refreshed for {session_data.get('user_name', 'User')}.\n"
            f"Paper trading active for today. 🟢"
        )
        logger.info("Login complete.")

    except Exception as e:
        logger.error(f"Session generation failed: {e}")
        telegram_send(f"❌ <b>Kite login failed:</b> {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
