import json
import os
import sys
import requests

UIDPASS_FILE = "uidpass.json"
TOKEN_FILE = "tokens.json"

# BD / OB55 JWT generator — key লাগতে পারে
API_URL = os.environ.get("JWT_API_URL", "https://xtytdtyj-jwt.up.railway.app/token")
API_KEY = os.environ.get("JWT_API_KEY", "")


def read_uidpass():
    with open(UIDPASS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_token(uid: str, password: str):
    params = {"uid": uid, "password": password}
    if API_KEY:
        params["key"] = API_KEY
    try:
        r = requests.get(API_URL, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("token")
    except Exception as e:
        print(f"[!] {uid}: {e}")
        return None


def main():
    rows = read_uidpass()
    fresh = []
    for row in rows:
        token = fetch_token(row["uid"], row["password"])
        if token:
            fresh.append({"token": token})
        else:
            print(f"[skip] {row['uid']}")

    if not fresh:
        print("no tokens — check uidpass.json / JWT_API_KEY / API_URL")
        sys.exit(1)

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(fresh, f, ensure_ascii=False, indent=4)

    print(f"tokens.json updated — {len(fresh)} token(s)")


if __name__ == "__main__":
    main()