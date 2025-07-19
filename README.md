# Robinhood_Crypto_Bot

Automated DCA / take‑profit crypto trader for the Robinhood Crypto API.

## Features
* Signs every request with Ed25519 (Robinhood requirement)
* Dynamic cost‑basis tracking
* Multi‑level DCA ladder
* Auto profit‑taking at ≥ 5 % gain

## Quick start

```bash
# 1. install deps
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. run
python rh_crypto_bot.py
